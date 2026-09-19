//! The selected capture: immutable source, the useful-for line, the derived
//! stub, and the three things you can do with it.

use dioxus::prelude::*;
use wasm_bindgen_futures::JsFuture;

use crate::api;
use crate::i18n::{t, t1, t2};
use crate::inbox::{report, Inbox};
use crate::toast;

#[component]
pub fn Detail() -> Element {
    let mut state = use_context::<Inbox>();

    let detail = use_resource(move || {
        let selected = (state.selected)();
        let _ = (state.revision)();
        async move {
            match selected {
                // `preview` keeps a 1 MiB capture off the wire on every
                // selection; Copy asks for the whole body separately.
                Some(id) => Some(api::source(&id, true).await),
                None => None,
            }
        }
    });

    let mut draft = use_signal(String::new);
    let mut draft_for = use_signal(|| None::<String>);
    let mut confirming = use_signal(|| false);
    let mut saving = use_signal(|| false);

    // Reset the field only when a different capture opens, so a refetch after
    // a write does not wipe what is being typed.
    use_effect(move || {
        let Some(Some(Ok(loaded))) = detail() else { return };
        if draft_for.peek().as_deref() != Some(loaded.source_id.as_str()) {
            draft.set(loaded.context.clone().unwrap_or_default());
            draft_for.set(Some(loaded.source_id.clone()));
        }
    });

    let Some(loaded) = detail() else {
        return rsx! { div { class: "empty", p { class: "empty-lead", "…" } } };
    };

    let loaded = match loaded {
        None => {
            return rsx! {
                div { class: "empty", p { class: "empty-lead", "{t(\"list.select\")}" } }
            }
        }
        Some(Err(err)) => {
            return rsx! {
                p { class: "banner banner-error", role: "alert", "{t(&err.message_key())}" }
            }
        }
        Some(Ok(loaded)) => loaded,
    };

    let source_id = loaded.source_id.clone();
    let capture_id = loaded.latest_capture_id.clone();
    let used = loaded.used_count > 0;

    let save_context = move |event: Event<FormData>| {
        event.prevent_default();
        if saving() {
            return;
        }
        let id = (state.selected)();
        let body = draft();
        let Some(id) = id else { return };
        saving.set(true);
        spawn(async move {
            match api::save_context(&id, &body).await {
                Ok(()) => {
                    toast::ok(t("context.saved"));
                    state.refresh();
                }
                Err(err) => report(&err),
            }
            saving.set(false);
        });
    };

    let copy_source = move |_| {
        let Some(id) = (state.selected)() else { return };
        spawn(async move {
            // Refetch without `preview` so the clipboard gets the real source,
            // not the display-truncated one.
            let full = match api::source(&id, false).await {
                Ok(full) => full,
                Err(err) => return report(&err),
            };
            if write_clipboard(&full.raw_body).await.is_err() {
                return toast::error(t("action.copy_failed"));
            }
            toast::ok(t("action.copied"));
            // Best-effort: a copy that reached the clipboard still counts even
            // if recording the reuse event fails.
            let _ = api::reuse(&id, "copy_source").await;
            state.refresh();
        });
    };

    let mark_used = move |_| {
        let Some(id) = (state.selected)() else { return };
        spawn(async move {
            match api::reuse(&id, "mark_used").await {
                Ok(()) => {
                    toast::ok(t("action.used"));
                    state.refresh();
                }
                Err(err) => report(&err),
            }
        });
    };

    let confirm_delete = move |_| {
        let Some(id) = capture_id.clone() else { return };
        confirming.set(false);
        spawn(async move {
            match api::delete_capture(&id).await {
                Ok(()) => {
                    toast::ok(t("action.deleted"));
                    // The open capture may be gone; let the list pick the next.
                    state.selected.set(None);
                    state.close();
                    state.refresh();
                }
                Err(err) => report(&err),
            }
        });
    };

    rsx! {
        article { class: "detail",
            div { class: "detail-head",
                button {
                    class: "btn btn-quiet detail-back",
                    r#type: "button",
                    onclick: move |_| state.close(),
                    "← {t(\"action.back\")}"
                }
                h2 { class: "detail-title", "{first_line(&loaded.raw_body)}" }
                div { class: "detail-facts",
                    span { class: "pill pill-kind", "{loaded.kind}" }
                    if loaded.occurrence_count > 1 {
                        span {
                            class: "pill",
                            "{t1(\"list.captured_n\", \"n\", &loaded.occurrence_count.to_string())}"
                        }
                    }
                    if used {
                        span { class: "pill pill-used", "{t(\"action.used\")}" }
                    }
                }
            }

            div { class: "panels",
                section { class: "panel",
                    h3 { class: "panel-title", "{t(\"source.heading\")}" }
                    pre { class: "source-body", "{loaded.raw_body}" }
                    if loaded.truncated {
                        p { class: "note",
                            "{t2(\"digest.truncated\", [(\"shown\", &loaded.raw_body.chars().count().to_string()), (\"total\", &loaded.raw_chars.to_string())])}"
                        }
                    }
                }

                section { class: "panel panel-side",
                    h3 { class: "panel-title", "{t(\"digest.heading\")}" }
                    match loaded.digest.as_ref() {
                        Some(digest) => rsx! {
                            p { class: "digest-summary", "{digest.summary}" }
                            p { class: "note", "model: {digest.model} · prompt: {digest.prompt_id}" }
                        },
                        None => rsx! { p { class: "note", "{t(\"digest.none\")}" } },
                    }
                }
            }

            form { class: "context-form", onsubmit: save_context,
                label { class: "field-label", r#for: "context-body", "{t(\"context.heading\")}" }
                div { class: "context-row",
                    input {
                        id: "context-body",
                        class: "field",
                        r#type: "text",
                        maxlength: "200",
                        placeholder: "{t(\"context.placeholder\")}",
                        value: "{draft}",
                        onmounted: move |event| state.context_ref.set(Some(event.data())),
                        onfocus: move |_| state.text_focus(true),
                        onblur: move |_| state.text_focus(false),
                        oninput: move |event| draft.set(event.value()),
                    }
                    button { class: "btn", r#type: "submit", disabled: saving(),
                        "{t(\"context.save\")}"
                    }
                }
            }

            div { class: "actions",
                button { class: "btn btn-primary", r#type: "button", onclick: copy_source,
                    "{t(\"action.copy\")}"
                }
                button { class: "btn", r#type: "button", onclick: mark_used,
                    if used { "{t(\"action.mark_used_again\")}" } else { "{t(\"action.mark_used\")}" }
                }
                button {
                    class: "btn btn-danger",
                    r#type: "button",
                    disabled: loaded.latest_capture_id.is_none(),
                    onclick: move |_| confirming.set(true),
                    "{t(\"action.delete\")}"
                }
            }

            if confirming() {
                // An in-app dialog instead of window.confirm: the old native
                // prompt could not be styled and read as a browser warning.
                div { class: "scrim", onclick: move |_| confirming.set(false),
                    div {
                        class: "card dialog",
                        role: "alertdialog",
                        "aria-modal": "true",
                        onclick: move |event| event.stop_propagation(),

                        p { class: "dialog-body", "{t(\"action.delete_confirm\")}" }
                        div { class: "dialog-actions",
                            button {
                                class: "btn",
                                r#type: "button",
                                onclick: move |_| confirming.set(false),
                                "{t(\"action.cancel\")}"
                            }
                            button { class: "btn btn-danger", r#type: "button", onclick: confirm_delete,
                                "{t(\"action.delete\")}"
                            }
                        }
                    }
                }
            }

            p { class: "note detail-id", "{source_id}" }
        }
    }
}

fn first_line(body: &str) -> String {
    let line: String = body.lines().next().unwrap_or_default().chars().take(90).collect();
    if line.trim().is_empty() {
        t("list.untitled")
    } else {
        line
    }
}

async fn write_clipboard(text: &str) -> Result<(), ()> {
    let clipboard = web_sys::window().ok_or(())?.navigator().clipboard();
    JsFuture::from(clipboard.write_text(text)).await.map(|_| ()).map_err(|_| ())
}
