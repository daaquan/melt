//! Light/dark selection, persisted per browser.
//!
//! The stylesheet defines both palettes and follows `prefers-color-scheme` by
//! default; this only pins an explicit override onto `<html data-theme>`.

use dioxus::prelude::*;

const KEY: &str = "melt.theme";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Theme {
    System,
    Light,
    Dark,
}

impl Theme {
    fn as_str(self) -> &'static str {
        match self {
            Theme::System => "system",
            Theme::Light => "light",
            Theme::Dark => "dark",
        }
    }

    fn parse(value: &str) -> Theme {
        match value {
            "light" => Theme::Light,
            "dark" => Theme::Dark,
            _ => Theme::System,
        }
    }

    /// Cycles system → light → dark → system, so one control covers all three
    /// without a menu.
    pub fn next(self) -> Theme {
        match self {
            Theme::System => Theme::Light,
            Theme::Light => Theme::Dark,
            Theme::Dark => Theme::System,
        }
    }

    pub fn label_key(self) -> &'static str {
        match self {
            Theme::System => "theme.system",
            Theme::Light => "theme.light",
            Theme::Dark => "theme.dark",
        }
    }
}

fn storage() -> Option<web_sys::Storage> {
    web_sys::window()?.local_storage().ok().flatten()
}

pub fn load() -> Theme {
    storage()
        .and_then(|store| store.get_item(KEY).ok().flatten())
        .map(|value| Theme::parse(&value))
        .unwrap_or(Theme::System)
}

pub fn apply(theme: Theme) {
    let Some(document) = web_sys::window().and_then(|window| window.document()) else {
        return;
    };
    let Some(root) = document.document_element() else {
        return;
    };
    // `data-theme` absent means "follow the OS", which is what the media query
    // in app.css already handles.
    let _ = match theme {
        Theme::System => root.remove_attribute("data-theme"),
        other => root.set_attribute("data-theme", other.as_str()),
    };
    if let Some(store) = storage() {
        let _ = store.set_item(KEY, theme.as_str());
    }
}

/// Keeps the signal and the DOM attribute in step for the life of the app.
pub fn use_theme() -> Signal<Theme> {
    let theme = use_signal(load);
    use_effect(move || apply(theme()));
    theme
}
