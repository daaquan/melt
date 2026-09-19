//! Locale strings, fetched once from `/v1/i18n`.
//!
//! The design doc keeps user-facing English out of source and in `locales/`,
//! so the client carries keys only and looks every string up at render time.

use dioxus::prelude::*;
use std::collections::HashMap;

pub static CATALOG: GlobalSignal<HashMap<String, String>> = Global::new(HashMap::new);

/// A missing key renders as the key itself, which makes the gap obvious in the
/// UI instead of silently showing nothing.
pub fn t(key: &str) -> String {
    CATALOG
        .read()
        .get(key)
        .cloned()
        .unwrap_or_else(|| key.to_string())
}

/// `{name}` substitution, matching the `str.format` placeholders the Python
/// side uses on the same catalog.
pub fn t1(key: &str, name: &str, value: &str) -> String {
    t(key).replace(&format!("{{{name}}}"), value)
}

pub fn t2(key: &str, pairs: [(&str, &str); 2]) -> String {
    let mut out = t(key);
    for (name, value) in pairs {
        out = out.replace(&format!("{{{name}}}"), value);
    }
    out
}

/// Coarse "how long ago" for list rows. Exact timestamps are noise when the
/// whole point is "the thing I copied a minute ago".
pub fn relative_time(captured_at_ms: f64) -> String {
    let elapsed = (js_sys::Date::now() - captured_at_ms).max(0.0) / 1000.0;
    if elapsed < 60.0 {
        return t("time.just_now");
    }
    let minutes = elapsed / 60.0;
    if minutes < 60.0 {
        return t1("time.minutes", "n", &format!("{}", minutes as i64));
    }
    let hours = minutes / 60.0;
    if hours < 24.0 {
        return t1("time.hours", "n", &format!("{}", hours as i64));
    }
    let days = hours / 24.0;
    if days < 7.0 {
        return t1("time.days", "n", &format!("{}", days as i64));
    }
    t1("time.weeks", "n", &format!("{}", (days / 7.0) as i64))
}
