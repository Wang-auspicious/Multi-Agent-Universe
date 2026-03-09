const state = {
  bootstrap: null,
  fileTree: [],
  includeArchives: false,
  fileQuery: "",
  openTabs: [],
  activePath: "",
  activeChatId: "",
  activeTaskId: "",
  activeHistoryId: "",
  activeArtifactIndex: -1,
  activeTraceIndex: -1,
  drawer: "diff",
  assistantView: "agent",
  pollHandle: null,
};

const els = {};

function byId(id) {
  return document.getElementById(id);
}

function initEls() {
  [
    "repoNameTop", "repoNameSide", "branchBadge", "modifiedBadge", "fileQuery", "includeArchives", "fileTree",
    "editorTabs", "currentPath", "reloadFile", "saveFile", "lineNumbers", "editorInput", "diffOutput",
    "findSnippet", "replaceSnippet", "snippetCount", "copySelectionToFind", "copySelectionToReplace", "applySnippet",
    "historyList", "historyDiff", "refreshHistory", "rollbackHistory", "chatSelect", "executorSelect", "messageStream",
    "taskTitle", "taskMeta", "taskSummary", "artifactList", "artifactDetail", "traceRail", "tracePayload", "taskPrompt",
    "statusText", "runTaskButton", "newChatButton", "statusLeft", "fileCountStatus", "taskCountStatus", "chatCountStatus",
    "refreshExplorer", "executorHealth"
  ].forEach((id) => { els[id] = byId(id); });
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

function setStatus(text) {
  els.statusText.textContent = text;
  els.statusLeft.textContent = text;
}

function trimText(value, limit = 120) {
  const clean = (value || "").replace(/\s+/g, " ").trim();
  return clean.length <= limit ? clean : `${clean.slice(0, limit - 3)}...`;
}

function currentTab() {
  return state.openTabs.find((tab) => tab.path === state.activePath) || null;
}

function ensureTab(path, content = "") {
  let tab = state.openTabs.find((item) => item.path === path);
  if (!tab) {
    tab = { path, original: content, content, history: [] };
    state.openTabs.push(tab);
  }
  return tab;
}

function renderBootstrap() {
  const boot = state.bootstrap;
  if (!boot) return;
  els.repoNameTop.textContent = boot.repo_name;
  els.repoNameSide.textContent = boot.repo_name;
  els.branchBadge.textContent = boot.git.branch || "detached";
  els.modifiedBadge.textContent = `${(boot.git.modified || []).length} modified`;
  els.fileCountStatus.textContent = `${state.fileTree.length} nodes`;
  els.taskCountStatus.textContent = `${(boot.tasks || []).length} tasks`;
  els.chatCountStatus.textContent = `${(boot.chats || []).length} chats`;

  const healthy = (boot.executors || []).filter((row) => row.ok).map((row) => row.name);
  els.executorHealth.textContent = healthy.length ? `${healthy.length} ready` : "offline";

  els.executorSelect.innerHTML = "";
  (boot.executors || []).forEach((row) => {
    const option = document.createElement("option");
    option.value = row.name;
    option.textContent = row.ok ? row.name : `${row.name} (offline)`;
    els.executorSelect.appendChild(option);
  });

  const previousChat = state.activeChatId;
  els.chatSelect.innerHTML = "";
  (boot.chats || []).forEach((chat) => {
    const option = document.createElement("option");
    option.value = chat.chat_id;
    option.textContent = trimText(chat.title || chat.chat_id, 48);
    els.chatSelect.appendChild(option);
  });
  if (!state.activeChatId && boot.chats && boot.chats.length) {
    state.activeChatId = boot.chats[0].chat_id;
  }
  if (previousChat && (boot.chats || []).some((row) => row.chat_id === previousChat)) {
    state.activeChatId = previousChat;
  }
  if (state.activeChatId) {
    els.chatSelect.value = state.activeChatId;
  }
}

async function loadBootstrap() {
  state.bootstrap = await fetchJson("/api/bootstrap");
  renderBootstrap();
}

function flattenTree(nodes, collector = []) {
  nodes.forEach((node) => {
    collector.push(node);
    if (node.children) flattenTree(node.children, collector);
  });
  return collector;
}

function renderTree(nodes, host, depth = 0) {
  host.innerHTML = "";
  nodes.forEach((node) => {
    const wrapper = document.createElement("div");
    wrapper.className = `tree-node ${node.type === "dir" ? "tree-folder" : "tree-file"}`;
    const row = document.createElement("div");
    row.className = `tree-row ${node.path === state.activePath ? "active" : ""}`;
    row.style.marginLeft = `${depth * 10}px`;
    row.innerHTML = `
      <span class="tree-toggle">${node.type === "dir" ? "▾" : ""}</span>
      <span class="tree-icon">${node.type === "dir" ? "⌄" : "•"}</span>
      <span class="tree-name">${node.name}</span>
    `;
    wrapper.appendChild(row);
    if (node.type === "file") {
      row.addEventListener("click", () => openFile(node.path));
    } else {
      const children = document.createElement("div");
      children.className = "tree-children";
      renderTree(node.children || [], children, depth + 1);
      wrapper.appendChild(children);
      row.addEventListener("click", () => {
        const hidden = children.style.display === "none";
        children.style.display = hidden ? "block" : "none";
        row.querySelector(".tree-toggle").textContent = hidden ? "▾" : "▸";
      });
    }
    host.appendChild(wrapper);
  });
}

async function loadExplorer() {
  const query = encodeURIComponent(els.fileQuery.value.trim());
  const include = els.includeArchives.checked ? "1" : "0";
  const data = await fetchJson(`/api/explorer?include_archives=${include}&q=${query}`);
  state.fileTree = flattenTree(data.tree || []);
  renderTree(data.tree || [], els.fileTree);
  els.fileCountStatus.textContent = `${data.count || 0} files`;
}

function renderTabs() {
  els.editorTabs.innerHTML = "";
  state.openTabs.forEach((tab) => {
    const button = document.createElement("button");
    const dirty = tab.content !== tab.original;
    button.className = `editor-tab ${tab.path === state.activePath ? "active" : ""} ${dirty ? "dirty" : ""}`;
    button.innerHTML = `<span class="name">${tab.path.split("/").pop()}</span><span class="close">×</span>`;
    button.addEventListener("click", (event) => {
      if (event.target.classList.contains("close")) {
        closeTab(tab.path);
        event.stopPropagation();
        return;
      }
      state.activePath = tab.path;
      renderEditor();
    });
    els.editorTabs.appendChild(button);
  });
}

function updateLineNumbers(content) {
  const count = Math.max(1, content.split("\n").length);
  const lines = [];
  for (let i = 1; i <= count; i += 1) lines.push(String(i));
  els.lineNumbers.textContent = lines.join("\n");
}

async function refreshDiff() {
  const tab = currentTab();
  if (!tab) {
    els.diffOutput.textContent = "Open a file to inspect its buffer diff.";
    return;
  }
  const payload = await fetchJson("/api/file/diff", {
    method: "POST",
    body: JSON.stringify({ path: tab.path, before: tab.original, after: tab.content }),
  });
  els.diffOutput.textContent = payload.diff || "";
}

function renderHistory(tab) {
  els.historyList.innerHTML = "";
  (tab?.history || []).forEach((row) => {
    const item = document.createElement("div");
    item.className = `history-item ${row.id === state.activeHistoryId ? "active" : ""}`;
    item.textContent = `${row.operation}  ${row.id}  ${row.timestamp || ""}`;
    item.addEventListener("click", () => {
      state.activeHistoryId = row.id;
      renderHistory(tab);
      els.historyDiff.textContent = row.diff || "No diff stored for this entry.";
    });
    els.historyList.appendChild(item);
  });
  if (!tab?.history?.length) {
    els.historyDiff.textContent = "No patch history for the current file yet.";
  }
}

function renderEditor() {
  renderTabs();
  const tab = currentTab();
  if (!tab) {
    els.currentPath.textContent = "No file selected";
    els.editorInput.value = "";
    updateLineNumbers("");
    els.diffOutput.textContent = "Open a file to inspect its buffer diff.";
    els.historyList.innerHTML = "";
    els.historyDiff.textContent = "No patch history for the current file yet.";
    return;
  }
  els.currentPath.textContent = tab.path;
  els.editorInput.value = tab.content;
  updateLineNumbers(tab.content);
  renderHistory(tab);
  if (!state.activeHistoryId && tab.history && tab.history.length) {
    state.activeHistoryId = tab.history[0].id;
    els.historyDiff.textContent = tab.history[0].diff || "No diff stored for this entry.";
  }
  refreshDiff();
}

async function openFile(path) {
  const payload = await fetchJson(`/api/file?path=${encodeURIComponent(path)}`);
  if (!payload.ok) {
    setStatus(payload.error || "Unable to open file.");
    return;
  }
  const tab = ensureTab(path, payload.content || "");
  tab.original = payload.content || "";
  tab.content = payload.content || "";
  tab.history = payload.history || [];
  state.activePath = path;
  state.activeHistoryId = tab.history?.[0]?.id || "";
  renderEditor();
  loadExplorer();
}

function closeTab(path) {
  state.openTabs = state.openTabs.filter((tab) => tab.path !== path);
  if (state.activePath === path) {
    state.activePath = state.openTabs[0]?.path || "";
  }
  renderEditor();
}

async function saveCurrentFile() {
  const tab = currentTab();
  if (!tab) return;
  const payload = await fetchJson("/api/file/save", {
    method: "POST",
    body: JSON.stringify({ path: tab.path, content: tab.content }),
  });
  if (!payload.ok) {
    setStatus(payload.error || "Save failed.");
    return;
  }
  tab.original = tab.content;
  tab.history = payload.history || [];
  state.activeHistoryId = tab.history?.[0]?.id || "";
  renderEditor();
  setStatus(`Saved ${tab.path}`);
}

async function reloadCurrentFile() {
  const tab = currentTab();
  if (!tab) return;
  await openFile(tab.path);
  setStatus(`Reloaded ${tab.path}`);
}

async function applySnippetPatch() {
  const tab = currentTab();
  if (!tab) return;
  const payload = await fetchJson("/api/file/patch", {
    method: "POST",
    body: JSON.stringify({
      path: tab.path,
      find: els.findSnippet.value,
      replace: els.replaceSnippet.value,
      count: Number(els.snippetCount.value || 1),
    }),
  });
  if (!payload.ok) {
    setStatus(payload.error || "Patch failed.");
    return;
  }
  tab.original = payload.content || "";
  tab.content = payload.content || "";
  tab.history = payload.history || [];
  state.activeHistoryId = tab.history?.[0]?.id || "";
  renderEditor();
  setStatus(`Patched ${tab.path}`);
}

async function rollbackHistory() {
  const tab = currentTab();
  if (!tab || !state.activeHistoryId) return;
  const payload = await fetchJson("/api/file/rollback", {
    method: "POST",
    body: JSON.stringify({ path: tab.path, entry_id: state.activeHistoryId }),
  });
  if (!payload.ok) {
    setStatus(payload.error || "Rollback failed.");
    return;
  }
  tab.original = payload.content || "";
  tab.content = payload.content || "";
  tab.history = payload.history || [];
  state.activeHistoryId = tab.history?.[0]?.id || "";
  renderEditor();
  setStatus(`Rolled back ${tab.path}`);
}

async function loadChat(chatId) {
  if (!chatId) {
    els.messageStream.innerHTML = "";
    return;
  }
  const payload = await fetchJson(`/api/chat/${encodeURIComponent(chatId)}`);
  state.activeChatId = chatId;
  els.chatSelect.value = chatId;
  els.messageStream.innerHTML = "";
  (payload.messages || []).forEach((message) => {
    const card = document.createElement("div");
    card.className = `message ${message.role === "user" ? "user" : "assistant"}`;
    card.innerHTML = `
      <div class="message-role">${message.role}${message.task_id ? ` • ${message.task_id}` : ""}</div>
      <div class="message-text"></div>
    `;
    card.querySelector(".message-text").textContent = message.content || "";
    card.addEventListener("click", () => {
      if (message.task_id) loadTask(message.task_id);
    });
    els.messageStream.appendChild(card);
  });
  els.messageStream.scrollTop = els.messageStream.scrollHeight;
}

function renderArtifacts(artifacts) {
  els.artifactList.innerHTML = "";
  (artifacts || []).forEach((artifact, index) => {
    const row = document.createElement("div");
    row.className = `artifact-item ${index === state.activeArtifactIndex ? "active" : ""}`;
    row.textContent = trimText(`${artifact.kind || "artifact"} ${artifact.content || artifact.stdout || ""}`, 70);
    row.addEventListener("click", () => {
      state.activeArtifactIndex = index;
      renderArtifacts(artifacts);
      const detail = JSON.stringify(artifact, null, 2);
      const diff = artifact.content ? "" : (artifact.stdout || "");
      els.artifactDetail.textContent = diff.includes("@@") ? `${detail}\n\n${diff}` : detail;
    });
    els.artifactList.appendChild(row);
  });
  if (artifacts && artifacts.length && state.activeArtifactIndex < 0) {
    state.activeArtifactIndex = 0;
    renderArtifacts(artifacts);
    return;
  }
  if (!artifacts || !artifacts.length) {
    els.artifactDetail.textContent = "No artifacts for the selected task yet.";
  }
}

function renderTrace(events) {
  els.traceRail.innerHTML = "";
  (events || []).forEach((event, index) => {
    const item = document.createElement("div");
    item.className = `trace-item ${index === state.activeTraceIndex ? "active" : ""}`;
    item.innerHTML = `
      <div class="trace-type">${event.event_type}</div>
      <div class="trace-meta">${event.created_at || ""}</div>
    `;
    item.addEventListener("click", () => {
      state.activeTraceIndex = index;
      renderTrace(events);
      els.tracePayload.textContent = JSON.stringify(event, null, 2);
    });
    els.traceRail.appendChild(item);
  });
  if (events && events.length && state.activeTraceIndex < 0) {
    state.activeTraceIndex = 0;
    renderTrace(events);
    return;
  }
  if (!events || !events.length) {
    els.tracePayload.textContent = "No trace events yet.";
  }
}

async function loadTask(taskId) {
  if (!taskId) return;
  const payload = await fetchJson(`/api/task/${encodeURIComponent(taskId)}`);
  state.activeTaskId = taskId;
  state.activeArtifactIndex = -1;
  state.activeTraceIndex = -1;
  const task = payload.task || {};
  const live = payload.live || {};
  els.taskTitle.textContent = task.goal || taskId;
  els.taskMeta.textContent = live.running ? `running • ${live.last_event || "working"}` : (task.status || live.status || "idle");
  els.taskSummary.textContent = payload.summary || task.summary || payload.checkpoint?.summary || "No summary yet.";
  renderArtifacts(payload.artifacts || []);
  renderTrace(payload.events || []);
  if (payload.checkpoint?.chat_id) {
    state.activeChatId = payload.checkpoint.chat_id;
    els.chatSelect.value = payload.checkpoint.chat_id;
    await loadChat(payload.checkpoint.chat_id);
  }
}

async function runTask() {
  const goal = els.taskPrompt.value.trim();
  if (!goal) {
    setStatus("Enter a task goal first.");
    return;
  }
  const payload = await fetchJson("/api/task/run", {
    method: "POST",
    body: JSON.stringify({
      goal,
      executor: els.executorSelect.value,
      chat_id: state.activeChatId,
    }),
  });
  state.activeTaskId = payload.task_id;
  state.activeChatId = payload.chat_id;
  els.taskPrompt.value = "";
  setStatus(`Running ${payload.task_id}`);
  await loadBootstrap();
  await loadChat(payload.chat_id);
  await loadTask(payload.task_id);
}

function selectDrawer(name) {
  state.drawer = name;
  document.querySelectorAll(".drawer-tab").forEach((button) => button.classList.toggle("active", button.dataset.drawer === name));
  document.querySelectorAll(".drawer-view").forEach((view) => view.classList.toggle("active", view.dataset.drawerView === name));
}

function selectAssistantView(name) {
  state.assistantView = name;
  document.querySelectorAll(".assistant-tab").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  document.querySelectorAll(".assistant-view").forEach((view) => view.classList.toggle("active", view.dataset.viewPanel === name));
}

function bindEvents() {
  els.refreshExplorer.addEventListener("click", loadExplorer);
  els.fileQuery.addEventListener("input", loadExplorer);
  els.includeArchives.addEventListener("change", loadExplorer);
  els.saveFile.addEventListener("click", saveCurrentFile);
  els.reloadFile.addEventListener("click", reloadCurrentFile);
  els.editorInput.addEventListener("input", () => {
    const tab = currentTab();
    if (!tab) return;
    tab.content = els.editorInput.value;
    updateLineNumbers(tab.content);
    renderTabs();
    refreshDiff();
  });
  els.editorInput.addEventListener("scroll", () => {
    els.lineNumbers.scrollTop = els.editorInput.scrollTop;
  });
  els.copySelectionToFind.addEventListener("click", () => {
    const start = els.editorInput.selectionStart;
    const end = els.editorInput.selectionEnd;
    els.findSnippet.value = els.editorInput.value.slice(start, end);
  });
  els.copySelectionToReplace.addEventListener("click", () => {
    const start = els.editorInput.selectionStart;
    const end = els.editorInput.selectionEnd;
    els.replaceSnippet.value = els.editorInput.value.slice(start, end);
  });
  els.applySnippet.addEventListener("click", applySnippetPatch);
  els.refreshHistory.addEventListener("click", () => openFile(state.activePath));
  els.rollbackHistory.addEventListener("click", rollbackHistory);
  els.chatSelect.addEventListener("change", () => loadChat(els.chatSelect.value));
  els.newChatButton.addEventListener("click", async () => {
    state.activeChatId = "";
    els.messageStream.innerHTML = "";
    setStatus("Started a new chat thread.");
  });
  els.runTaskButton.addEventListener("click", runTask);
  document.querySelectorAll(".drawer-tab").forEach((button) => button.addEventListener("click", () => selectDrawer(button.dataset.drawer)));
  document.querySelectorAll(".assistant-tab").forEach((button) => button.addEventListener("click", () => selectAssistantView(button.dataset.view)));
}

async function poll() {
  try {
    await loadBootstrap();
    if (state.activeChatId) await loadChat(state.activeChatId);
    if (state.activeTaskId) await loadTask(state.activeTaskId);
  } catch (error) {
    setStatus(error.message || String(error));
  }
}

async function boot() {
  initEls();
  bindEvents();
  await loadBootstrap();
  await loadExplorer();
  if (state.activeChatId) await loadChat(state.activeChatId);
  selectDrawer("diff");
  selectAssistantView("agent");
  setStatus("Cursor-style local workbench ready.");
  if (state.pollHandle) clearInterval(state.pollHandle);
  state.pollHandle = setInterval(poll, 2500);
}

document.addEventListener("DOMContentLoaded", boot);
