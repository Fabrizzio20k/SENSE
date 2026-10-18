"""Contratos de preparación con archivos y HTTP simulados; sin hardware ni red."""

import asyncio
import base64
import hashlib
import io
import json
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
from PIL import Image

from app import RunCommand
from orchestrator import Conflict
from prepare import ensure_yolo
from runtime import Runtime, Settings
from slm import CompletedResponseError, NoRequestError, SLM
from vision import validate_ncnn


def export_fixture(path, size=320):
    path.mkdir(parents=True)
    (path/"model.ncnn.param").write_text("fixture; no executable graph")
    (path/"model.ncnn.bin").write_bytes(b"fixture weights")
    (path/"metadata.yaml").write_text(f"imgsz: [{size}, {size}]\nnames:\n  0: person\n")


class PreparationTests(unittest.TestCase):
    def test_existing_export_needs_no_exporter_and_is_not_inference_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/"model_ncnn_model"
            export_fixture(target)
            with patch.dict("sys.modules", {"ultralytics": None, "ncnn": None}):
                report = ensure_yolo(target, Path(directory)/"yolo26n.pt", 320)
            self.assertEqual(report["preparation"], "reused_existing_export")
            self.assertFalse(report["inference_verified"])
            self.assertEqual(len(report["files_sha256"]), 3)

    def test_invalid_export_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/"model_ncnn_model"
            export_fixture(target, 640)
            original = {p.name: p.read_bytes() for p in target.iterdir()}
            with self.assertRaises(ValueError):
                ensure_yolo(target, Path(directory)/"yolo26n.pt", 320)
            self.assertEqual(original, {p.name: p.read_bytes() for p in target.iterdir()})
            (target/"metadata.yaml").write_text("imgsz: [")
            with self.assertRaisesRegex(ValueError, "YAML"):
                validate_ncnn(target, 320)
            (target/"model.ncnn.bin").write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "vacíos"):
                validate_ncnn(target, 320)

    def test_missing_export_is_built_once_with_original_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/"requested_ncnn_model"
            weights = Path(directory)/"cache/yolo26n.pt"
            previous_cwd = Path.cwd()
            def fake_export(**kwargs):
                Path("yolo26n.pt").write_bytes(b"downloaded weights fixture")
                result = Path.cwd()/"yolo26n_ncnn_model"
                export_fixture(result)
                return str(result)
            model = Mock()
            model.export.side_effect = fake_export
            factory = Mock(return_value=model)
            with patch.dict("sys.modules", {"ultralytics": Mock(YOLO=factory), "ncnn": Mock()}), \
                 patch("prepare.importlib.metadata.version", return_value="fixture"), patch.dict("os.environ", {}):
                report = ensure_yolo(target, weights, 320)
                again = ensure_yolo(target, weights, 320)
            factory.assert_called_once_with("yolo26n.pt")
            model.export.assert_called_once_with(format="ncnn", imgsz=320, quantize=16, device="cpu")
            self.assertEqual(Path.cwd(), previous_cwd)
            self.assertEqual(weights.read_bytes(), b"downloaded weights fixture")
            self.assertEqual(again["preparation"], "reused_existing_export")
            provenance = json.loads((target/"preparation.json").read_text())
            self.assertEqual(provenance["weights_sha256"], report["weights_sha256"])
            self.assertEqual(provenance["measurement_scope"], "setup_outside_experimental_runs")

    def test_failed_conversion_does_not_publish_partial_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target, weights = Path(directory)/"model_ncnn_model", Path(directory)/"local.pt"
            weights.write_bytes(b"local fixture")
            model = Mock()
            model.export.side_effect = RuntimeError("conversion failed")
            previous_cwd = Path.cwd()
            with patch.dict("sys.modules", {"ultralytics": Mock(YOLO=Mock(return_value=model)), "ncnn": Mock()}), \
                 patch.dict("os.environ", {}), self.assertRaises(RuntimeError):
                ensure_yolo(target, weights, 320)
            self.assertFalse(target.exists())
            self.assertEqual(weights.read_bytes(), b"local fixture")
            self.assertEqual(Path.cwd(), previous_cwd)


class GemmaProbeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.image_path = Path(self.directory.name)/"image.png"
        Image.new("RGB", (800, 400), "blue").save(self.image_path)

    async def asyncTearDown(self):
        self.directory.cleanup()

    async def test_catalog_check_never_generates(self):
        client_type = httpx.AsyncClient
        for payload, status in (({"data": [{"id": "gemma4-e2b"}]}, "ready"),
                                ({"data": [{"id": "other"}]}, "unavailable"),
                                ({"data": "invalid"}, "unavailable")):
            with self.subTest(payload=payload):
                requests = []
                def handler(request):
                    requests.append((request.method, str(request.url)))
                    return httpx.Response(200, json=payload)
                transport = httpx.MockTransport(handler)
                with patch("slm.httpx.AsyncClient", side_effect=lambda **kwargs: client_type(transport=transport, **kwargs)):
                    report = await SLM("http://127.0.0.1:8080", "gemma4-e2b", 120, 384).probe()
                self.assertEqual(report["status"], status)
                self.assertFalse(report["generation_verified"])
                self.assertEqual(requests, [("GET", "http://127.0.0.1:8080/v1/models")])

    async def test_connection_failure_is_diagnostic(self):
        with patch("slm.httpx.AsyncClient", side_effect=httpx.ConnectError("offline")):
            report = await SLM("http://127.0.0.1:8080", "gemma4-e2b", 120, 384).probe()
        self.assertEqual(report["status"], "unavailable")
        self.assertFalse(report["api_reachable"])

    async def test_warmup_sends_image_and_requests_one_word_without_thinking(self):
        client_type = httpx.AsyncClient
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"model": "gemma4-e2b", "usage": {"completion_tokens": 1},
                "choices": [{"finish_reason": "stop", "message": {"content": "Gato"}}]})
        with patch("slm.httpx.AsyncClient", side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs)):
            report = await SLM("http://127.0.0.1:8080", "gemma4-e2b", 120, 384).warmup(self.image_path)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].method, "POST")
        self.assertEqual(requests[0].url.path, "/v1/chat/completions")
        body = json.loads(requests[0].content)
        content = body["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("una sola palabra", content[0]["text"])
        self.assertEqual(content[1]["type"], "image_url")
        header, encoded = content[1]["image_url"]["url"].split(",", 1)
        self.assertEqual(header, "data:image/jpeg;base64")
        jpeg = base64.b64decode(encoded)
        with Image.open(io.BytesIO(jpeg)) as image:
            self.assertEqual(image.size, (480, 240))
        self.assertEqual(body["max_completion_tokens"], 16)
        self.assertEqual(body["reasoning_effort"], "none")
        self.assertFalse(body["stream"])
        self.assertTrue(report["generation_verified"])
        self.assertFalse(report["visual_encoder_verified"])
        self.assertTrue(report["image_request_completed"])
        self.assertEqual(report["profile_id"], "gemma-image-warmup-v1")
        self.assertEqual(report["image_input"]["source_sha256"], hashlib.sha256(self.image_path.read_bytes()).hexdigest())
        self.assertEqual(report["image_input"]["sha256"], hashlib.sha256(jpeg).hexdigest())
        self.assertEqual(report["measurement_scope"], "setup_outside_experimental_runs")

    async def test_warmup_rejects_incomplete_thinking_or_wrong_responses(self):
        client_type = httpx.AsyncClient
        for reason, message in (("length", {"content": "Gato"}), ("stop", {"content": ""}),
                                ("stop", {"content": "dos palabras"}), ("stop", {"content": "<think>x</think>Gato"}),
                                ("stop", {"content": "Gato", "reasoning_content": "thinking"}),
                                ("stop", {"content": "Gato", "tool_calls": [{"id": "unexpected"}]})):
            with self.subTest(reason=reason, message=message):
                transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
                    "choices": [{"finish_reason": reason, "message": message}]}))
                with patch("slm.httpx.AsyncClient", side_effect=lambda **kwargs: client_type(transport=transport, **kwargs)):
                    with self.assertRaises(CompletedResponseError):
                        await SLM("http://127.0.0.1:8080", "gemma4-e2b", 120, 384).warmup(self.image_path)

    async def test_missing_or_corrupt_warmup_image_never_calls_http(self):
        for path in (Path(self.directory.name)/"missing.png", self.image_path):
            with self.subTest(path=path):
                if path == self.image_path:
                    path.write_bytes(b"not an image")
                with patch("slm.httpx.AsyncClient") as client:
                    with self.assertRaises(NoRequestError):
                        await SLM("http://127.0.0.1:8080", "gemma4-e2b", 120, 384).warmup(path)
                    client.assert_not_called()

    async def test_missing_pillow_is_an_error_before_any_request(self):
        with patch.dict("sys.modules", {"PIL": None}), patch("slm.httpx.AsyncClient") as client:
            with self.assertRaisesRegex(NoRequestError, "Pillow"):
                await SLM("http://127.0.0.1:8080", "gemma4-e2b", 120, 384).warmup(self.image_path)
            client.assert_not_called()

    async def test_interpretation_keeps_its_schema_and_evidence_validation_on_shared_transport(self):
        client_type = httpx.AsyncClient
        interpretation = {"status": "supported", "observed": [{"claim": "El radar declara presencia.", "evidence_ids": ["radar-1"]}],
                          "inferred": [], "unknown": [], "requested_information": [], "recommendations": [], "answer": "Presencia declarada."}
        snapshot = {"snapshot_id": "snapshot-1", "sources": {"ld2410c": {
            "usable_for_reported_values": True, "latest": {"observation_id": "radar-1", "values": {"state_code": 2}}}}}
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(interpretation)}}]})
        with patch("slm.httpx.AsyncClient", side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs)):
            report = await SLM("http://127.0.0.1:8080", "gemma4-e2b", 120, 384).interpret(snapshot, "¿Hay presencia?")
        self.assertEqual(report["validated"], interpretation)
        self.assertEqual(requests[0]["max_completion_tokens"], 384)
        self.assertEqual(requests[0]["response_format"], {"type": "json_object"})


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = Runtime(Settings(data_dir=Path(self.directory.name)))

    async def asyncTearDown(self):
        await self.runtime.close()
        self.directory.cleanup()

    async def test_concurrent_admissions_cannot_prepare_during_another_run(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def preparation(**kwargs):
            entered.set()
            await release.wait()
            self.runtime.preflight = {"yolo": {"status": "ready"}, "gemma": {"status": "ready"}}
        request = RunCommand(variant="C").model_dump()
        with patch.object(self.runtime, "_prepare_dependencies", side_effect=preparation) as prepare:
            first = asyncio.create_task(self.runtime.admit(request, "first"))
            await entered.wait()
            second = asyncio.create_task(self.runtime.admit(request, "second"))
            release.set()
            results = await asyncio.gather(first, second, return_exceptions=True)
            self.assertIsInstance(results[0], str)
            self.assertIsInstance(results[1], Conflict)
            self.assertEqual(await self.runtime.admit(request, "first"), results[0])
            prepare.assert_awaited_once()

    async def test_replay_rejected_before_model_preparation(self):
        self.runtime.settings.mode = "replay"
        with patch.object(self.runtime, "_prepare_dependencies", new_callable=AsyncMock) as prepare:
            with self.assertRaises(Conflict):
                await self.runtime.admit(RunCommand(variant="D", source_mode="replay").model_dump())
            prepare.assert_not_awaited()

    async def test_cancelled_preparation_stops_converter_process_group(self):
        process = Mock(pid=12345)
        process.wait = AsyncMock(side_effect=[asyncio.CancelledError(), 0, 0])
        with patch("runtime.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=process) as spawn, \
             patch("runtime.os.killpg") as kill:
            with self.assertRaises(asyncio.CancelledError):
                await self.runtime.prepare_dependencies(need_gemma=False)
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        self.assertEqual(kill.call_args_list[0].args, (12345, signal.SIGTERM))
        self.assertEqual(kill.call_args_list[1].args, (12345, signal.SIGKILL))
        self.assertFalse(self.runtime.admission_lock.locked())

    async def test_health_refreshes_status_and_skips_probe_inside_session(self):
        self.runtime.preflight = {"status": "ready", "yolo": {"status": "ready"}, "gemma": {"status": "ready"}}
        with patch.object(self.runtime.actions.slm, "probe", new_callable=AsyncMock, return_value={"status": "unavailable"}) as probe:
            self.assertEqual((await self.runtime.dependency_health())["status"], "degraded")
            await self.runtime.admit(RunCommand().model_dump())
            report = await self.runtime.dependency_health()
            self.assertIn("gemma_probe_skipped", report)
            probe.assert_awaited_once()

    async def test_warmup_is_outside_run_and_not_repeated_on_each_admission(self):
        request = RunCommand(variant="D").model_dump()
        target = Path(self.directory.name)/"model_ncnn_model"
        export_fixture(target)
        self.runtime.settings.vision_model = str(target)
        warmed = {"status": "ready", "generation_verified": True, "duration_s": .1}
        async def warmup(image_path, image_side):
            self.assertIsNone(self.runtime.engine.run_id)
            self.assertEqual(self.runtime.store.flag("slm_busy")["state"], "warmup_in_flight")
            self.assertEqual(image_path.name, "image.png")
            self.assertEqual(image_path.parent.name, "static")
            self.assertEqual(image_side, 480)
            return warmed
        with patch.object(self.runtime.actions.slm, "probe", new_callable=AsyncMock, return_value={"status": "ready"}), \
             patch.object(self.runtime.actions.slm, "warmup", side_effect=warmup) as generate:
            await self.runtime.prepare_dependencies()
            await self.runtime.admit(request)
            manifest = self.runtime.store.run(self.runtime.engine.run_id)["manifest"]
            self.assertEqual(manifest["preflight"]["gemma_warmup"], warmed)
            self.assertTrue(manifest["slm"]["warmup_enabled"])
            generate.assert_awaited_once()
        self.assertIsNone(self.runtime.store.flag("slm_busy"))

    async def test_disabled_warmup_never_generates(self):
        self.runtime.settings.slm_warmup = False
        with patch.object(self.runtime.actions.slm, "probe", new_callable=AsyncMock, return_value={"status": "ready"}), \
             patch.object(self.runtime.actions.slm, "warmup", new_callable=AsyncMock) as generate:
            report = await self.runtime.prepare_dependencies(need_yolo=False)
        self.assertEqual(report["gemma_warmup"]["status"], "disabled")
        generate.assert_not_awaited()

    async def test_warmup_failure_preserves_uncertain_reservation_but_completed_rejection_releases_it(self):
        for error, reserved in ((TimeoutError("remote unknown"), True), (asyncio.CancelledError(), True),
                                (CompletedResponseError("unexpected answer"), False), (NoRequestError("missing image"), False)):
            with self.subTest(error=type(error).__name__):
                self.runtime.store.flag("slm_busy", None, write=True)
                with patch.object(self.runtime.actions.slm, "probe", new_callable=AsyncMock, return_value={"status": "ready"}), \
                     patch.object(self.runtime.actions.slm, "warmup", new_callable=AsyncMock, side_effect=error) as generate:
                    if isinstance(error, asyncio.CancelledError):
                        with self.assertRaises(asyncio.CancelledError):
                            await self.runtime.prepare_dependencies(need_yolo=False)
                        report = self.runtime.preflight
                    else:
                        report = await self.runtime.prepare_dependencies(need_yolo=False)
                self.assertEqual(report["gemma_warmup"]["status"], "failed")
                self.assertEqual(bool(self.runtime.store.flag("slm_busy")), reserved)
                self.assertEqual(report["gemma_warmup"]["remote_stop_unconfirmed"], reserved)
                generate.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
