//! Transient feedback for actions that no longer reload the page.
//!
//! The server-rendered inbox reported success by navigating; a client-side UI
//! has to say so itself, so every mutation lands here.

use dioxus::prelude::*;
use gloo_timers::future::TimeoutFuture;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tone {
    Ok,
    Error,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Toast {
    pub id: u64,
    pub text: String,
    pub tone: Tone,
}

pub static TOASTS: GlobalSignal<Vec<Toast>> = Global::new(Vec::new);
static NEXT_ID: GlobalSignal<u64> = Global::new(|| 1);

const DWELL_MS: u32 = 3200;

pub fn push(text: impl Into<String>, tone: Tone) {
    let id = {
        let mut next = NEXT_ID.write();
        let id = *next;
        *next += 1;
        id
    };
    TOASTS.write().push(Toast { id, text: text.into(), tone });
    spawn(async move {
        TimeoutFuture::new(DWELL_MS).await;
        dismiss(id);
    });
}

pub fn ok(text: impl Into<String>) {
    push(text, Tone::Ok);
}

pub fn error(text: impl Into<String>) {
    push(text, Tone::Error);
}

pub fn dismiss(id: u64) {
    TOASTS.write().retain(|toast| toast.id != id);
}

#[component]
pub fn ToastHost() -> Element {
    rsx! {
        div { class: "toasts", role: "status", "aria-live": "polite",
            for toast in TOASTS.read().iter().cloned() {
                div {
                    key: "{toast.id}",
                    class: match toast.tone {
                        Tone::Ok => "toast toast-ok",
                        Tone::Error => "toast toast-error",
                    },
                    span { class: "toast-text", "{toast.text}" }
                    button {
                        class: "toast-close",
                        r#type: "button",
                        "aria-label": "dismiss",
                        onclick: move |_| dismiss(toast.id),
                        "×"
                    }
                }
            }
        }
    }
}
