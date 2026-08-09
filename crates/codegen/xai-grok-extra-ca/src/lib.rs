//! Cached native TLS roots plus opt-in extra roots via
//! `GROK_EXTRA_CA_BUNDLE` (PEM path).
//!
//! The extra bundle is default-off (unset/empty env → no bundle I/O), parsed
//! once into a process `OnceLock`, and additive to native and WebPKI roots.
//! Each DER is validated with
//! `rustls::RootCertStore::add` before caching so a bad bundle cannot fail
//! `ClientBuilder::build()`. Unreadable/oversized/empty/unparsable → warn and
//! continue. Size cap: [`MAX_EXTRA_CA_BUNDLE_BYTES`].
//!
//! Source of truth is validated DER ([`native_root_ders`] and
//! [`extra_root_ders`]) so callers can retain independent reqwest transports
//! and policies without repeatedly walking the operating-system trust store.

use std::io::Read;
use std::sync::OnceLock;

use rustls::RootCertStore;
use rustls::pki_types::CertificateDer;
use rustls::pki_types::pem::PemObject;

/// Hard cap on `GROK_EXTRA_CA_BUNDLE` (1 MiB) — avoids unbounded startup reads.
pub const MAX_EXTRA_CA_BUNDLE_BYTES: u64 = 1024 * 1024;

/// Env var name for the opt-in extra CA bundle (PEM path).
pub const ENV_GROK_EXTRA_CA_BUNDLE: &str = "GROK_EXTRA_CA_BUNDLE";

/// Set to `0` or `false` to restore reqwest's per-client native-root loading.
pub const ENV_GROK_CACHE_NATIVE_ROOTS: &str = "GROK_CACHE_NATIVE_ROOTS";

/// Process-wide extra roots as validated DER, parsed once.
///
/// Empty when the env var is unset/empty or the file yields no usable certs.
pub fn extra_root_ders() -> &'static [Vec<u8>] {
    static DERS: OnceLock<Vec<Vec<u8>>> = OnceLock::new();
    DERS.get_or_init(load_extra_root_ders).as_slice()
}

/// Process-wide native roots as validated DER, loaded once on first use.
///
/// Reqwest otherwise calls `rustls_native_certs::load_native_certs()` for every
/// `ClientBuilder::build()` when its native-roots feature is unified into the
/// binary. On macOS that synchronously walks the user, admin, and system trust
/// domains. Caching the immutable DER snapshot keeps separate clients/pools
/// cheap while preserving native enterprise CAs.
///
/// This is intentionally a process-lifetime snapshot. Native trust-store,
/// `SSL_CERT_FILE`, and `SSL_CERT_DIR` changes take effect after restart. Native
/// certificates that rustls cannot parse are skipped. If none are usable,
/// cached builders continue with WebPKI and [`extra_root_ders`] roots.
pub fn native_root_ders() -> &'static [Vec<u8>] {
    static DERS: OnceLock<Vec<Vec<u8>>> = OnceLock::new();
    DERS.get_or_init(load_native_root_ders).as_slice()
}

/// Apply process-cached native roots and [`extra_root_ders`] to a workspace
/// (reqwest 0.12) async `ClientBuilder`.
///
/// WebPKI roots remain enabled. Only reqwest's built-in native-root loading is
/// disabled, because the equivalent prevalidated native roots are injected
/// here. All other builder policy (proxy discovery, redirects, timeouts,
/// compression, and pool settings) is left untouched.
///
/// Set [`ENV_GROK_CACHE_NATIVE_ROOTS`] to `0` or `false` before process start
/// to restore reqwest's legacy per-builder loading. Like the cached roots, the
/// kill-switch value is read once and changes require restart.
pub fn with_cached_root_certificates(
    mut builder: reqwest::ClientBuilder,
) -> reqwest::ClientBuilder {
    if native_root_cache_disabled() {
        return with_extra_root_certificates(builder);
    }

    builder = builder.tls_built_in_native_certs(false);
    for der in native_root_ders() {
        match reqwest::Certificate::from_der(der) {
            Ok(cert) => builder = builder.add_root_certificate(cert),
            // WHY: rustls already accepted this DER; skip rather than poison build.
            Err(e) => tracing::warn!(
                error = %e,
                "cached native root rejected by reqwest; skipping cert"
            ),
        }
    }
    with_extra_root_certificates(builder)
}

fn native_root_cache_disabled() -> bool {
    static DISABLED: OnceLock<bool> = OnceLock::new();
    *DISABLED.get_or_init(|| {
        let disabled = cache_disabled_value(std::env::var_os(ENV_GROK_CACHE_NATIVE_ROOTS));
        if disabled {
            tracing::info!(
                "native TLS root caching disabled via {ENV_GROK_CACHE_NATIVE_ROOTS}; reqwest will load roots per client"
            );
        }
        disabled
    })
}

fn cache_disabled_value(value: Option<impl AsRef<std::ffi::OsStr>>) -> bool {
    value.is_some_and(|value| {
        let value = value.as_ref().to_string_lossy();
        value == "0" || value.eq_ignore_ascii_case("false")
    })
}

/// Apply [`extra_root_ders`] to a workspace (reqwest 0.12) async `ClientBuilder`.
pub fn with_extra_root_certificates(mut builder: reqwest::ClientBuilder) -> reqwest::ClientBuilder {
    for der in extra_root_ders() {
        match reqwest::Certificate::from_der(der) {
            Ok(cert) => builder = builder.add_root_certificate(cert),
            // WHY: rustls already accepted this DER; skip rather than poison build.
            Err(e) => tracing::warn!(
                error = %e,
                "GROK_EXTRA_CA_BUNDLE: validated DER rejected by reqwest; skipping cert"
            ),
        }
    }
    builder
}

/// Apply [`extra_root_ders`] to a workspace (reqwest 0.12) blocking `ClientBuilder`.
pub fn with_extra_root_certificates_blocking(
    mut builder: reqwest::blocking::ClientBuilder,
) -> reqwest::blocking::ClientBuilder {
    for der in extra_root_ders() {
        match reqwest::Certificate::from_der(der) {
            Ok(cert) => builder = builder.add_root_certificate(cert),
            // WHY: rustls already accepted this DER; skip rather than poison build.
            Err(e) => tracing::warn!(
                error = %e,
                "GROK_EXTRA_CA_BUNDLE: validated DER rejected by reqwest; skipping cert"
            ),
        }
    }
    builder
}

fn load_extra_root_ders() -> Vec<Vec<u8>> {
    let path = match std::env::var_os(ENV_GROK_EXTRA_CA_BUNDLE) {
        Some(p) if !p.is_empty() => std::path::PathBuf::from(p),
        _ => return Vec::new(),
    };

    let bytes = match read_bundle_capped(&path) {
        Ok(b) => b,
        Err(BundleReadError::Io(e)) => {
            // WHY: MITM CA is optional; a missing path must not brick HTTP.
            tracing::warn!(
                path = %path.display(),
                error = %e,
                "GROK_EXTRA_CA_BUNDLE unreadable; continuing without extra roots"
            );
            return Vec::new();
        }
        Err(BundleReadError::TooLarge) => {
            tracing::warn!(
                path = %path.display(),
                max_bytes = MAX_EXTRA_CA_BUNDLE_BYTES,
                "GROK_EXTRA_CA_BUNDLE exceeds size cap; continuing without extra roots"
            );
            return Vec::new();
        }
    };

    let outcome = parse_and_validate_pem(&bytes);
    if outcome.no_pem_blocks {
        tracing::warn!(
            path = %path.display(),
            "GROK_EXTRA_CA_BUNDLE contains no PEM certificate blocks; continuing without extra roots"
        );
        return outcome.accepted;
    }
    if outcome.rejected > 0 {
        tracing::warn!(
            path = %path.display(),
            accepted = outcome.accepted.len(),
            rejected = outcome.rejected,
            "GROK_EXTRA_CA_BUNDLE: dropped unusable certificate block(s)"
        );
    }
    if outcome.accepted.is_empty() {
        tracing::warn!(
            path = %path.display(),
            "GROK_EXTRA_CA_BUNDLE produced zero usable certificates; continuing without extra roots"
        );
    } else {
        tracing::info!(
            path = %path.display(),
            accepted = outcome.accepted.len(),
            "GROK_EXTRA_CA_BUNDLE: loaded extra root certificate(s)"
        );
    }
    outcome.accepted
}

fn load_native_root_ders() -> Vec<Vec<u8>> {
    #[cfg(test)]
    NATIVE_ROOT_LOADS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);

    let result = rustls_native_certs::load_native_certs();
    let error_count = result.errors.len();
    let (accepted, rejected) = validate_native_root_ders(result.certs);

    if error_count > 0 || rejected > 0 {
        tracing::debug!(
            accepted = accepted.len(),
            rejected,
            load_errors = error_count,
            "native TLS roots loaded with skipped entries"
        );
    }
    if accepted.is_empty() {
        tracing::warn!(
            rejected,
            load_errors = error_count,
            "native TLS root cache is empty; WebPKI and GROK_EXTRA_CA_BUNDLE roots remain available"
        );
    }

    accepted
}

fn validate_native_root_ders(certs: Vec<CertificateDer<'static>>) -> (Vec<Vec<u8>>, usize) {
    let mut store = RootCertStore::empty();
    let mut accepted = Vec::with_capacity(certs.len());
    let mut rejected = 0usize;

    for der in certs {
        match store.add(der.clone()) {
            Ok(()) => accepted.push(der.as_ref().to_vec()),
            Err(_) => rejected += 1,
        }
    }

    (accepted, rejected)
}

#[cfg(test)]
static NATIVE_ROOT_LOADS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

#[derive(Debug)]
enum BundleReadError {
    Io(std::io::Error),
    TooLarge,
}

fn read_bundle_capped(path: &std::path::Path) -> Result<Vec<u8>, BundleReadError> {
    let file = std::fs::File::open(path).map_err(BundleReadError::Io)?;
    let mut buf = Vec::new();
    let n = file
        .take(MAX_EXTRA_CA_BUNDLE_BYTES + 1)
        .read_to_end(&mut buf)
        .map_err(BundleReadError::Io)?;
    if (n as u64) > MAX_EXTRA_CA_BUNDLE_BYTES {
        return Err(BundleReadError::TooLarge);
    }
    Ok(buf)
}

/// Result of parsing a PEM bundle into rustls-validated DER roots.
#[derive(Debug, Default)]
pub(crate) struct ParseOutcome {
    pub(crate) accepted: Vec<Vec<u8>>,
    /// PEM blocks that failed decode or rustls X.509 validation.
    pub(crate) rejected: usize,
    /// Input (non-empty) contained no PEM certificate blocks at all.
    pub(crate) no_pem_blocks: bool,
}

/// Parse PEM into rustls-validated DER (no env / OnceLock). Input with no PEM
/// certificate blocks (including empty) → empty accepted, zero rejected,
/// `no_pem_blocks` set.
pub(crate) fn parse_and_validate_pem(pem: &[u8]) -> ParseOutcome {
    let mut accepted = Vec::new();
    let mut rejected = 0usize;
    let mut saw_block = false;

    // WHY: reject non-X.509 DER before any ClientBuilder sees it; `add`
    // validates per certificate, so one store serves the whole bundle.
    let mut store = RootCertStore::empty();
    for item in CertificateDer::pem_slice_iter(pem) {
        saw_block = true;
        match item {
            Ok(der) => match store.add(der.clone()) {
                Ok(()) => accepted.push(der.as_ref().to_vec()),
                Err(_) => rejected += 1,
            },
            Err(_) => rejected += 1,
        }
    }

    ParseOutcome {
        accepted,
        rejected,
        no_pem_blocks: !saw_block,
    }
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
