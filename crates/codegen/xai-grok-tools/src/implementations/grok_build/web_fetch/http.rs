//! Cached HTTP client with atomic invalidation for `web_fetch`.
//!
//! The `reqwest::Client` is held behind an `ArcSwapOption` so it can be
//! atomically invalidated on transport errors, forcing the next call to rebuild
//! with a fresh connection pool. This prevents connection pool poisoning
//! (half-read connections being returned to the pool and corrupting subsequent
//! requests).

use std::sync::Arc;

use arc_swap::ArcSwapOption;

use super::config::WebFetchParams;
use super::error::WebFetchError;

/// Cached, invalidatable HTTP client for web fetching.
///
/// - **Normal path:** `get_or_rebuild()` returns the cached client via a
///   lock-free atomic load.
/// - **On transport error:** call `invalidate()` to atomically set the
///   client to `None`. The next `get_or_rebuild()` falls through and
///   builds a fresh client with a clean connection pool.
#[derive(Clone, Debug)]
pub(crate) struct HttpClient {
    inner: Arc<ArcSwapOption<reqwest::Client>>,
    params: WebFetchParams,
}

impl HttpClient {
    pub(crate) fn new(params: &WebFetchParams) -> Result<Self, WebFetchError> {
        // Keep proxy configuration validation eager while deferring the
        // comparatively expensive TLS/client construction.
        let _ = Self::proxy(params)?;
        Ok(Self {
            inner: Arc::new(ArcSwapOption::empty()),
            params: params.clone(),
        })
    }

    /// Get the current client, building it on first use or after invalidation.
    pub(crate) fn get_or_rebuild(&self) -> Result<Arc<reqwest::Client>, WebFetchError> {
        // Fast path: lock-free atomic load.
        if let Some(client) = self.inner.load_full() {
            return Ok(client);
        }
        // Client is uninitialized or was invalidated — build a fresh pool.
        let fresh = Arc::new(Self::build(&self.params)?);
        self.inner.store(Some(Arc::clone(&fresh)));
        Ok(fresh)
    }

    /// Atomically invalidate the cached client. The next `get_or_rebuild()`
    /// will construct a fresh one with a clean connection pool.
    pub(crate) fn invalidate(&self) {
        self.inner.store(None);
    }

    fn build(params: &WebFetchParams) -> Result<reqwest::Client, WebFetchError> {
        let mut builder = xai_grok_extra_ca::with_cached_root_certificates(
            reqwest::Client::builder()
                .timeout(params.timeout_secs())
                .connect_timeout(std::time::Duration::from_secs(10))
                // We manage redirects for SSRF.
                .redirect(reqwest::redirect::Policy::none())
                .pool_max_idle_per_host(2)
                .pool_idle_timeout(std::time::Duration::from_secs(30))
                .tcp_nodelay(true)
                // Reduce size of incoming payloads.
                .gzip(true)
                .brotli(true)
                .deflate(true),
        );

        // Route all traffic through the egress proxy when configured.
        if let Some(proxy) = Self::proxy(params)? {
            builder = builder.proxy(proxy);
        }

        builder.build().map_err(WebFetchError::ClientBuildError)
    }

    fn proxy(params: &WebFetchParams) -> Result<Option<reqwest::Proxy>, WebFetchError> {
        params
            .proxy_endpoint
            .as_deref()
            .map(reqwest::Proxy::all)
            .transpose()
            .map_err(|e| WebFetchError::ProxyConfigError(e.to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn get_or_rebuild_returns_client() {
        let client = HttpClient::new(&WebFetchParams::default()).unwrap();
        assert!(client.inner.load_full().is_none());
        let http = client.get_or_rebuild().unwrap();
        assert!(Arc::strong_count(&http) >= 1);
        let cached = client.inner.load_full().expect("client should be cached");
        assert!(Arc::ptr_eq(&http, &cached));
    }

    #[test]
    fn invalidate_forces_rebuild() {
        let client = HttpClient::new(&WebFetchParams::default()).unwrap();
        let first = client.get_or_rebuild().unwrap();
        let first_ptr = Arc::as_ptr(&first);

        client.invalidate();

        let second = client.get_or_rebuild().unwrap();
        let second_ptr = Arc::as_ptr(&second);

        // After invalidation, we should get a different client instance.
        assert_ne!(first_ptr, second_ptr);
    }

    #[test]
    fn build_with_proxy_endpoint() {
        let params = WebFetchParams {
            proxy_endpoint: Some("https://proxy.corp.example.com".into()),
            ..Default::default()
        };
        // Should succeed — reqwest accepts the proxy URL.
        let client = HttpClient::new(&params).unwrap();
        assert!(client.inner.load_full().is_none());
        assert!(client.get_or_rebuild().is_ok());
    }

    #[test]
    fn build_without_proxy_is_default() {
        let params = WebFetchParams::default();
        assert!(params.proxy_endpoint.is_none());
        let client = HttpClient::new(&params).unwrap();
        assert!(client.inner.load_full().is_none());
        assert!(client.get_or_rebuild().is_ok());
    }

    #[test]
    fn build_with_invalid_proxy_endpoint() {
        let params = WebFetchParams {
            proxy_endpoint: Some("not a valid url".into()),
            ..Default::default()
        };
        let result = HttpClient::new(&params);
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(
            err.contains("proxy"),
            "Expected proxy-related error, got: {err}"
        );
    }
}
