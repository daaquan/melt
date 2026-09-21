//! The inbox: search on the left, the selected capture on the right.
//!
//! Every mutation bumps `revision`, and both resources read it, so one signal
//! drives the refetch that the old page got for free from a 303 redirect.

use std::rc::Rc;

use dioxus::prelude::*;
use gloo_timers::future::TimeoutFuture;

use crate::api::{self, ApiError, Row};
use crate::detail::Detail;
use crate::i18n::{relative_time, t, t1};
use crate::theme::{use_theme, Theme};
use crate::toast;

/// Long enough that a fast typist issues one query, short enough that the list
/// still feels live. `use_resource` drops the in-flight future on each
/// keystroke, so the wait restarts rather than queueing.
const DEBOUNCE_MS: u32 = 160;

#[derive(Clone, Copy)]
pub struct Inbox {
    pub query: Signal<String>,
    pub selected: Signal<Option<String>>,
    /// Whether the user actively opened a capture. A row is always selected so
    /// the desktop detail pane is never blank, but on a phone the panes swap,
    /// and an auto-selection must not shove the list off screen.
    pub opened: Signal<bool>,
    pub typing: Signal<bool>,
    pub revision: Signal<u64>,
    pub context_ref: Signal<Option<Rc<MountedData>>>,
}

impl Inbox {
    /// Refetches the list and the open capture after a write.
    pub fn refresh(&mut self) {
        self.revision += 1;
    }

    /// Marks focus as living in a text field, which mutes the single-key
    /// shortcuts. Tracking it ourselves also keeps IME composition safe: a
    /// half-typed Japanese word never reaches the `j`/`k` handler.
    pub fn text_focus(&mut self, active: bool) {
        self.typing.set(active);
    }

    pub fn open(&mut self, source_id: String) {
        self.selected.set(Some(source_id));
        self.opened.set(true);
    }

    /// Back out to the list on narrow screens; a no-op visually on desktop,
    /// where both panes are always up.
    pub fn close(&mut self) {
        self.opened.set(false);
    }
}

#[component]
pub fn InboxView(on_signout: EventHandler<()>) -> Element {
    let mut state = use_context_provider(|| Inbox {
        query: Signal::new(String::new()),
        selected: Signal::new(None),
        opened: Signal::new(false),
        typing: Signal::new(false),
        revision: Signal::new(0),
        context_ref: Signal::new(None),
    });

    let mut theme = use_theme();
    let mut search_ref = use_signal(|| None::<Rc<MountedData>>);
    let mut shell_ref = use_signal(|| None::<Rc<MountedData>>);

    let rows = use_resource(move || {
        let q = (state.query)();
        let _ = (state.revision)();
        async move {
            // Only typing needs the wait. An empty query is the list's resting
            // state — first paint, and clearing the box — so it goes straight out.
            if !q.is_empty() {
                TimeoutFuture::new(DEBOUNCE_MS).await;
            }
            api::inbox(&q).await
        }
    });

    // Keep a capture open at all times: the first row when nothing is chosen,
    // and again when the current choice falls out of the result set.
    use_effect(move || {
        let Some(Ok(rows)) = rows() else { return };
        let current = (state.selected).peek().clone();
        let still_listed = current
            .as_ref()
            .is_some_and(|id| rows.iter().any(|row| &row.source_id == id));
        if !still_listed {
            state.selected.set(rows.first().map(|row| row.source_id.clone()));
        }
    });

    // A cookie that stopped matching MELT_TOKEN should land on the gate, not on
    // a permanently empty list.
    use_effect(move || {
        if let Some(Err(err)) = rows() {
            if err.is_auth() {
                on_signout.call(());
            }
        }
    });

    let focus_search = move || {
        if let Some(node) = search_ref() {
            spawn(async move {
                let _ = node.set_focus(true).await;
            });
        }
    };

    let focus_context = move || {
        if let Some(node) = (state.context_ref)() {
            spawn(async move {
                let _ = node.set_focus(true).await;
            });
        }
    };

    // Moves the highlight by `delta` rows, clamped at both ends.
    let mut step = move |delta: i32| {
        let Some(Ok(listed)) = rows.peek().clone() else { return };
        if listed.is_empty() {
            return;
        }
        let current = (state.selected)
            .peek()
            .as_ref()
            .and_then(|id| listed.iter().position(|row| &row.source_id == id))
            .unwrap_or(0) as i32;
        let next = (current + delta).clamp(0, listed.len() as i32 - 1) as usize;
        state.selected.set(Some(listed[next].source_id.clone()));
    };

    let keys = move |event: Event<KeyboardData>| {
        let modifiers = event.modifiers();
        if modifiers.ctrl() || modifiers.meta() || modifiers.alt() {
            return;
        }
        // Inside a text field only Escape means anything; everything else is
        // the user writing.
        if (state.typing)() {
            if event.key() == Key::Escape {
                event.prevent_default();
                state.typing.set(false);
                if let Some(node) = shell_ref() {
                    spawn(async move {
                        let _ = node.set_focus(true).await;
                    });
                }
            }
            return;
        }
        match event.key() {
            Key::ArrowDown => {
                event.prevent_default();
                step(1);
            }
            Key::ArrowUp => {
                event.prevent_default();
                step(-1);
            }
            Key::Character(ref c) => match c.as_str() {
                "j" => step(1),
                "k" => step(-1),
                "/" => {
                    event.prevent_default();
                    focus_search();
                }
                "n" => {
                    event.prevent_default();
                    focus_context();
                }
                _ => {}
            },
            _ => {}
        }
    };

    let query_value = (state.query)();
    let searching = !query_value.is_empty();

    // Under the narrow breakpoint the panes swap instead of sitting side by
    // side, and this class is what tells the stylesheet which one is showing.
    let shell_class = if (state.opened)() { "shell shell-detail" } else { "shell" };

    rsx! {
        div {
            class: "{shell_class}",
            tabindex: "-1",
            onkeydown: keys,
            onmounted: move |event| {
                // The shortcut handler lives on this node, and keydown only
                // bubbles from inside it, so the shell takes focus on load.
                let node = event.data();
                shell_ref.set(Some(node.clone()));
                spawn(async move {
                    let _ = node.set_focus(true).await;
                });
            },

            header { class: "topbar",
                span { class: "mark", "{t(\"app.name\")}" }
                div { class: "search",
                    label { class: "visually-hidden", r#for: "q", "{t(\"search.placeholder\")}" }
                    input {
                        id: "q",
                        class: "field search-field",
                        r#type: "search",
                        autocomplete: "off",
                        placeholder: "{t(\"search.placeholder\")}",
                        value: "{query_value}",
                        onmounted: move |event| search_ref.set(Some(event.data())),
                        onfocus: move |_| state.text_focus(true),
                        onblur: move |_| state.text_focus(false),
                        oninput: move |event| state.query.set(event.value()),
                    }
                    if searching {
                        button {
                            class: "search-clear",
                            r#type: "button",
                            "aria-label": "{t(\"search.clear\")}",
                            onclick: move |_| state.query.set(String::new()),
                            "×"
                        }
                    }
                }
                button {
                    class: "btn btn-quiet",
                    r#type: "button",
                    title: "{t(theme().label_key())}",
                    onclick: move |_| theme.set(theme().next()),
                    "{theme_glyph(theme())}"
                }
                button {
                    class: "btn btn-quiet",
                    r#type: "button",
                    onclick: move |_| {
                        spawn(async move {
                            let _ = api::logout().await;
                            on_signout.call(());
                        });
                    },
                    "{t(\"action.sign_out\")}"
                }
            }

            main { class: "panes",
                section { class: "list-pane", "aria-label": "{t(\"list.label\")}",
                    match rows() {
                        None => rsx! { SkeletonList {} },
                        Some(Err(err)) => rsx! {
                            p { class: "banner banner-error", role: "alert", "{t(&err.message_key())}" }
                        },
                        Some(Ok(listed)) if listed.is_empty() => rsx! {
                            EmptyList { query: query_value.clone() }
                        },
                        Some(Ok(listed)) => rsx! {
                            ul { class: "rows",
                                for row in listed {
                                    RowItem { key: "{row.source_id}", row: row.clone() }
                                }
                            }
                        },
                    }
                }
                section { class: "detail-pane", Detail {} }
            }
        }
    }
}

fn theme_glyph(theme: Theme) -> &'static str {
    match theme {
        Theme::System => "◐",
        Theme::Light => "○",
        Theme::Dark => "●",
    }
}

#[component]
fn RowItem(row: Row) -> Element {
    let mut state = use_context::<Inbox>();
    let active = (state.selected)().as_deref() == Some(row.source_id.as_str());
    let source_id = row.source_id.clone();

    rsx! {
        li {
            button {
                class: if active { "row row-active" } else { "row" },
                r#type: "button",
                "aria-current": if active { "true" } else { "false" },
                onclick: move |_| state.open(source_id.clone()),

                span { class: "row-title", "{row.title}" }
                span { class: "row-meta",
                    span { class: "row-time", "{relative_time(row.captured_at)}" }
                    if row.occurrence_count > 1 {
                        span {
                            class: "pill",
                            "{t1(\"list.captured_n\", \"n\", &row.occurrence_count.to_string())}"
                        }
                    }
                    if row.used_count > 0 {
                        span { class: "pill pill-used", "{t(\"action.used\")}" }
                    }
                }
                if let Some(context) = row.context.as_ref().filter(|value| !value.is_empty()) {
                    span { class: "row-context", "{context}" }
                }
            }
        }
    }
}

#[component]
fn EmptyList(query: String) -> Element {
    rsx! {
        div { class: "empty",
            if query.is_empty() {
                p { class: "empty-lead", "{t(\"list.empty\")}" }
                p { class: "empty-hint", "{t(\"list.empty_setup\")}" }
            } else {
                p { class: "empty-lead", "{t1(\"list.no_matches\", \"q\", &query)}" }
            }
        }
    }
}

/// Placeholder rows while the first fetch is in flight. Keeps the list column
/// from collapsing and then snapping back to full height.
#[component]
fn SkeletonList() -> Element {
    rsx! {
        // Deliberately not `.row`: a placeholder must not be selectable as a
        // capture, by a stylesheet, a test, or assistive tech.
        ul { class: "rows", "aria-hidden": "true",
            for index in 0..6 {
                li { key: "{index}",
                    div { class: "row-skeleton",
                        span { class: "skeleton skeleton-title" }
                        span { class: "skeleton skeleton-meta" }
                    }
                }
            }
        }
    }
}

/// Shared by the detail pane: report a failed write without losing the view.
pub fn report(err: &ApiError) {
    toast::error(t(&err.message_key()));
}
