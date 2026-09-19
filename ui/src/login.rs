//! Token gate. Posts to the same `/v1/login` route the server already owned,
//! so the cookie stays HttpOnly and the token never lives in JS state.

use dioxus::prelude::*;

use crate::api;
use crate::i18n::t;

#[component]
pub fn Login(on_success: EventHandler<()>) -> Element {
    let mut token = use_signal(String::new);
    let mut error = use_signal(|| None::<String>);
    let mut busy = use_signal(|| false);

    let submit = move |event: Event<FormData>| {
        event.prevent_default();
        if busy() {
            return;
        }
        let value = token();
        busy.set(true);
        error.set(None);
        spawn(async move {
            match api::login(&value).await {
                Ok(()) => {
                    token.set(String::new());
                    on_success.call(());
                }
                Err(err) => {
                    // A token mismatch is the expected failure here, so name it
                    // rather than falling through to the generic capture copy.
                    let key = if err.is_auth() { "login.error".to_string() } else { err.message_key() };
                    error.set(Some(t(&key)));
                }
            }
            busy.set(false);
        });
    };

    rsx! {
        main { class: "gate",
            form { class: "card gate-card", onsubmit: submit,
                h1 { class: "gate-title", "{t(\"login.title\")}" }
                p { class: "gate-sub", "{t(\"login.token_hint\")}" }

                if let Some(message) = error() {
                    p { class: "banner banner-error", role: "alert", "{message}" }
                }

                label { class: "field-label", r#for: "token", "{t(\"login.token_label\")}" }
                input {
                    id: "token",
                    class: "field",
                    r#type: "password",
                    autocomplete: "current-password",
                    autofocus: true,
                    required: true,
                    value: "{token}",
                    oninput: move |event| token.set(event.value()),
                }

                button { class: "btn btn-primary", r#type: "submit", disabled: busy(),
                    if busy() { "…" } else { "{t(\"login.submit\")}" }
                }
            }
        }
    }
}
