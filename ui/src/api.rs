//! Thin typed wrapper over the melt JSON API.
//!
//! Every error the server can raise is one flat problem object with a `code`
//! field (see docs/troubleshooting.md), so failures collapse to `ApiError` and
//! the UI renders `error.<code>.body` straight out of the locale catalog.

use gloo_net::http::{Request, Response};
use serde::Deserialize;
use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq)]
pub struct ApiError {
    pub status: u16,
    pub code: String,
}

impl ApiError {
    /// The fetch itself never reached the server (offline, container down).
    fn unreachable() -> Self {
        Self { status: 0, code: "api_unreachable".into() }
    }

    /// A cookie that no longer matches MELT_TOKEN drops the session.
    pub fn is_auth(&self) -> bool {
        self.status == 401 || self.status == 403
    }

    /// Locale key for the human-readable line.
    pub fn message_key(&self) -> String {
        format!("error.{}.body", self.code)
    }
}

#[derive(Deserialize)]
struct Problem {
    code: Option<String>,
}

async fn send(request: Result<Request, gloo_net::Error>) -> Result<Response, ApiError> {
    let request = request.map_err(|_| ApiError::unreachable())?;
    let response = request.send().await.map_err(|_| ApiError::unreachable())?;
    if response.ok() {
        return Ok(response);
    }
    let status = response.status();
    // A 401 from the auth dependency and a 413 from the size middleware share
    // the same shape, so one branch reads `code` off either.
    let code = response
        .json::<Problem>()
        .await
        .ok()
        .and_then(|problem| problem.code)
        // Not `generic`: that catalog line points at the host helper's
        // failed.jsonl, which means nothing in a browser.
        .unwrap_or_else(|| "unknown".to_string());
    Err(ApiError { status, code })
}

async fn get_json<T: serde::de::DeserializeOwned>(url: &str) -> Result<T, ApiError> {
    let response = send(Request::get(url).build()).await?;
    response.json::<T>().await.map_err(|_| ApiError::unreachable())
}

async fn post_json<T: serde::Serialize>(url: &str, body: &T) -> Result<Response, ApiError> {
    send(Request::post(url).json(body)).await
}

// --- models ---

#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Row {
    pub source_id: String,
    pub kind: String,
    pub title: String,
    pub captured_at: f64,
    pub occurrence_count: i64,
    pub used_count: i64,
    pub context: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
struct InboxPage {
    rows: Vec<Row>,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Digest {
    pub summary: String,
    pub model: String,
    pub prompt_id: String,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Detail {
    pub source_id: String,
    pub kind: String,
    /// Truncated to the server's display budget when fetched with `preview`.
    pub raw_body: String,
    /// Length of the untruncated body, so the UI can say what it is hiding.
    pub raw_chars: i64,
    pub truncated: bool,
    pub digest: Option<Digest>,
    pub context: Option<String>,
    pub occurrence_count: i64,
    pub used_count: i64,
    pub latest_capture_id: Option<String>,
}

#[derive(Deserialize)]
struct CatalogPage {
    catalog: HashMap<String, String>,
}

#[derive(Deserialize)]
struct SessionState {
    authenticated: bool,
}

// --- calls ---

/// UI strings. Unauthenticated: the login screen needs them before there is a
/// session, and the catalog holds no capture data.
pub async fn catalog() -> Result<HashMap<String, String>, ApiError> {
    Ok(get_json::<CatalogPage>("/v1/i18n").await?.catalog)
}

/// Cheap "is this cookie still good?" probe for the boot path. Unauthenticated
/// so a missing session answers `false` instead of an error.
pub async fn session() -> Result<bool, ApiError> {
    Ok(get_json::<SessionState>("/v1/session").await?.authenticated)
}

pub async fn logout() -> Result<(), ApiError> {
    send(Request::post("/v1/logout").build()).await?;
    Ok(())
}

pub async fn inbox(q: &str) -> Result<Vec<Row>, ApiError> {
    let url = format!("/v1/inbox?q={}", encode(q));
    Ok(get_json::<InboxPage>(&url).await?.rows)
}

/// `preview` caps `raw_body` at the server's display budget. Copy-to-clipboard
/// asks without it so the clipboard gets the whole source, never the preview.
pub async fn source(source_id: &str, preview: bool) -> Result<Detail, ApiError> {
    let url = format!(
        "/v1/sources/{}{}",
        encode(source_id),
        if preview { "?preview=1" } else { "" }
    );
    get_json::<Detail>(&url).await
}

pub async fn save_context(source_id: &str, body: &str) -> Result<(), ApiError> {
    let url = format!("/v1/sources/{}/context", encode(source_id));
    post_json(&url, &serde_json::json!({ "body": body })).await?;
    Ok(())
}

pub async fn reuse(source_id: &str, kind: &str) -> Result<(), ApiError> {
    let url = format!("/v1/sources/{}/reuse", encode(source_id));
    post_json(&url, &serde_json::json!({ "kind": kind })).await?;
    Ok(())
}

pub async fn delete_capture(capture_id: &str) -> Result<(), ApiError> {
    let url = format!("/v1/captures/{}", encode(capture_id));
    send(Request::delete(&url).build()).await?;
    Ok(())
}

/// Posts the same form body the no-JS page used to, so the token goes straight
/// into the HttpOnly cookie and never lands in JS state. `Accept` is what tells
/// the server this is a fetch: it answers 204 with the cookie instead of the
/// redirect a browser form needs, which fetch would follow into the whole shell.
pub async fn login(token: &str) -> Result<(), ApiError> {
    let body = format!("token={}", encode(token));
    let request = Request::post("/v1/login")
        .header("Content-Type", "application/x-www-form-urlencoded")
        .header("Accept", "application/json")
        .body(body);
    send(request).await?;
    Ok(())
}

fn encode(value: &str) -> String {
    String::from(js_sys::encode_uri_component(value))
}
