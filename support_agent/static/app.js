const state = {
  conversations: [],
  activeId: null,
  sending: false,
};

const elements = {
  conversationList: document.querySelector("#conversationList"),
  conversationTitle: document.querySelector("#conversationTitle"),
  messages: document.querySelector("#messages"),
  emptyState: document.querySelector("#emptyState"),
  messageForm: document.querySelector("#messageForm"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  newConversation: document.querySelector("#newConversation"),
  deleteConversation: document.querySelector("#deleteConversation"),
  providerLabel: document.querySelector("#providerLabel"),
  sidebar: document.querySelector("#sidebar"),
  openSidebar: document.querySelector("#openSidebar"),
  closeSidebar: document.querySelector("#closeSidebar"),
  toast: document.querySelector("#toast"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  window.setTimeout(() => elements.toast.classList.remove("visible"), 3200);
}

function preview(text) {
  return (text || "No messages yet").replace(/\s+/g, " ").slice(0, 62);
}

function renderConversations() {
  elements.conversationList.replaceChildren();
  for (const conversation of state.conversations) {
    const button = document.createElement("button");
    button.className = `conversation-item${conversation.id === state.activeId ? " active" : ""}`;
    button.type = "button";
    button.addEventListener("click", () => selectConversation(conversation.id));

    const avatar = document.createElement("span");
    avatar.className = "conversation-avatar";
    avatar.textContent = (conversation.title || "N").trim().charAt(0).toUpperCase();

    const copy = document.createElement("span");
    copy.className = "conversation-copy";
    const title = document.createElement("span");
    title.className = "conversation-title";
    title.textContent = conversation.title;
    const detail = document.createElement("span");
    detail.className = "conversation-preview";
    detail.textContent = preview(conversation.last_message);
    copy.append(title, detail);
    button.append(avatar, copy);
    elements.conversationList.append(button);
  }
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date);
}

function messageElement(message) {
  const row = document.createElement("article");
  row.className = `message-row ${message.role}`;
  const cluster = document.createElement("div");
  cluster.className = "message-cluster";
  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = `${message.role === "user" ? "You" : "智能客服助手"} · ${formatTime(message.created_at)}`;
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = message.content;
  cluster.append(meta, bubble);

  if (message.role === "assistant" && message.route && message.route !== "answer") {
    const badge = document.createElement("span");
    badge.className = "route-badge";
    badge.textContent = message.route;
    cluster.append(badge);
  }
  if (message.role === "assistant" && message.citations?.length) {
    const citations = document.createElement("div");
    citations.className = "citations";
    citations.textContent = `Evidence: ${message.citations.map((item) => item.title).join(" · ")}`;
    cluster.append(citations);
  }
  row.append(cluster);
  return row;
}

function renderMessages(messages) {
  elements.messages.replaceChildren();
  if (!messages.length) {
    elements.messages.append(elements.emptyState);
  } else {
    for (const message of messages) elements.messages.append(messageElement(message));
  }
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function renderTyping() {
  const row = document.createElement("article");
  row.className = "message-row assistant";
  row.id = "typingIndicator";
  const cluster = document.createElement("div");
  cluster.className = "message-cluster";
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  const typing = document.createElement("span");
  typing.className = "typing";
  typing.append(document.createElement("span"), document.createElement("span"), document.createElement("span"));
  bubble.append(typing);
  cluster.append(bubble);
  row.append(cluster);
  elements.messages.append(row);
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

async function refreshConversations() {
  const payload = await api("/api/conversations");
  state.conversations = payload.conversations;
  renderConversations();
}

async function createConversation() {
  const conversation = await api("/api/conversations", {
    method: "POST",
    body: JSON.stringify({}),
  });
  await refreshConversations();
  await selectConversation(conversation.id);
  elements.messageInput.focus();
}

async function selectConversation(id) {
  state.activeId = id;
  const payload = await api(`/api/conversations/${id}/messages`);
  elements.conversationTitle.textContent = payload.conversation.title;
  renderMessages(payload.messages);
  renderConversations();
  elements.sidebar.classList.remove("open");
}

async function sendMessage(content) {
  if (state.sending || !content.trim()) return;
  if (!state.activeId) await createConversation();
  state.sending = true;
  elements.sendButton.disabled = true;
  elements.messageInput.value = "";
  resizeInput();

  const optimistic = {
    role: "user",
    content: content.trim(),
    created_at: new Date().toISOString(),
    citations: [],
  };
  if (elements.messages.contains(elements.emptyState)) elements.messages.replaceChildren();
  elements.messages.append(messageElement(optimistic));
  renderTyping();

  try {
    const payload = await api(`/api/conversations/${state.activeId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    document.querySelector("#typingIndicator")?.remove();
    elements.messages.append(messageElement(payload.assistant_message));
    elements.messages.scrollTop = elements.messages.scrollHeight;
    await refreshConversations();
    const current = state.conversations.find((item) => item.id === state.activeId);
    if (current) elements.conversationTitle.textContent = current.title;
  } catch (error) {
    document.querySelector("#typingIndicator")?.remove();
    showToast(error.message);
    await selectConversation(state.activeId);
  } finally {
    state.sending = false;
    elements.sendButton.disabled = false;
    elements.messageInput.focus();
  }
}

async function deleteCurrentConversation() {
  if (!state.activeId) return;
  if (!window.confirm("Delete this conversation and its local message history?")) return;
  await api(`/api/conversations/${state.activeId}`, { method: "DELETE" });
  state.activeId = null;
  await refreshConversations();
  if (state.conversations.length) await selectConversation(state.conversations[0].id);
  else await createConversation();
}

function resizeInput() {
  elements.messageInput.style.height = "auto";
  elements.messageInput.style.height = `${Math.min(elements.messageInput.scrollHeight, 150)}px`;
}

elements.messageForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(elements.messageInput.value);
});
elements.messageInput.addEventListener("input", resizeInput);
elements.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.messageForm.requestSubmit();
  }
});
elements.newConversation.addEventListener("click", createConversation);
elements.deleteConversation.addEventListener("click", deleteCurrentConversation);
elements.openSidebar.addEventListener("click", () => elements.sidebar.classList.add("open"));
elements.closeSidebar.addEventListener("click", () => elements.sidebar.classList.remove("open"));
document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => sendMessage(button.dataset.prompt));
});

async function bootstrap() {
  try {
    const health = await api("/api/health");
    elements.providerLabel.textContent = `${health.provider} · ${health.synthetic_demo ? "虚构演示资料" : "自定义知识库"}`;
    await refreshConversations();
    if (state.conversations.length) await selectConversation(state.conversations[0].id);
    else await createConversation();
  } catch (error) {
    elements.providerLabel.textContent = "Disconnected";
    showToast(error.message);
  }
}

bootstrap();
