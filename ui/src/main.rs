//! melt's inbox, as a Dioxus client.
//!
//! FastAPI serves a static shell plus JSON; everything below `/` is rendered
//! here. Strings come from `locales/` over `/v1/i18n`, never from this source.

mod api;
mod detail;
mod i18n;
mod inbox;
mod login;
mod theme;
mod toast;

use dioxus::prelude::*;

use i18n::t;
use inbox::InboxView;
use login::Login;
use toast::ToastHost;

fn main() {
    dioxus::launch(App);
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Session {
    Loading,
    Anonymous,
    Active,
    /// The shell loaded but the API did not answer — worth saying plainly
    /// rather than showing a token prompt that cannot succeed.
    Offline,
}

#[component]
fn App() -> Element {
    let mut session = use_signal(|| Session::Loading);
    let mut booted = use_signal(|| false);

    let boot = move || {
        spawn(async move {
            if let Ok(catalog) = api::catalog().await {
                *i18n::CATALOG.write() = catalog;
            }
            session.set(match api::session().await {
                Ok(true) => Session::Active,
                Ok(false) => Session::Anonymous,
                Err(_) => Session::Offline,
            });
            booted.set(true);
        });
    };

    use_hook(boot);

    rsx! {
        ToastHost {}
        match session() {
            Session::Loading => rsx! {
                div { class: "gate", div { class: "boot", "aria-busy": "true" } }
            },
            Session::Offline => rsx! {
                main { class: "gate",
                    div { class: "card gate-card",
                        h1 { class: "gate-title", "{t(\"app.name\")}" }
                        p { class: "banner banner-error", role: "alert",
                            "{t(\"error.api_unreachable.body\")}"
                        }
                        button {
                            class: "btn btn-primary",
                            r#type: "button",
                            onclick: move |_| {
                                session.set(Session::Loading);
                                boot();
                            },
                            "{t(\"action.retry\")}"
                        }
                    }
                }
            },
            Session::Anonymous => rsx! {
                Login { on_success: move |_| session.set(Session::Active) }
            },
            Session::Active => rsx! {
                InboxView { on_signout: move |_| session.set(Session::Anonymous) }
            },
        }
    }
}
