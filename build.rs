fn main() {
    let rustc = std::env::var_os("RUSTC").unwrap_or("rustc".into());
    let output = std::process::Command::new(rustc)
        .arg("--version")
        .output()
        .expect("No se pudo consultar rustc");
    println!(
        "cargo:rustc-env=SENSE_RUST_VERSION={}",
        String::from_utf8_lossy(&output.stdout).trim()
    );
    println!("cargo:rerun-if-changed=Cargo.lock");
    println!("cargo:rerun-if-changed=Cargo.toml");
}
