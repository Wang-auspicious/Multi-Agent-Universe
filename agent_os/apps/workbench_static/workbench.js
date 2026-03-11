
const state = {
  bootstrap: null,
  treeRoots: [],
  includeArchives: false,
  fileQuery: "",
  openTabs: [],
  activePath: "",
  activeChatId: "",
  activeTaskId: "",
  activeHistoryId: "",
  activeArtifactIndex: -1,
  activeTraceIndex: -1,
  bottomPanel: "changes",
  assistantView: "agent",
  pollHandle: null,
  terminalResult: null,
  expandedDirs: new Set(),
  composerContext: {
    file: true,
    selection: true,
    terminal: false,
  },
  explorerLoaded: false,
  diffTimer: null,
  explorerTimer: null,
};

const els = {};

function byId(id) {
  return document.getElementById(id);
}

function initEls() {
  [
    "repoNameTop",
    "repoNameSide",
    "branchBadge",
    "modifiedBadge",
    "fileQuery",
    "includeArchives",
    "fileTree",
    "editorTabs",
    "reloadFile",
    "saveFile",
    "currentPath",
    "editorStatusChip",
    "breadcrumbs",
    "lineNumbers",
    "editorInput",
    "diffOutput",
    "findSnippet",
    "replaceSnippet",
    "snippetCount",
    "copySelectionToFind",
    "copySelectionToReplace",
    "applySnippet",
    "historyList",
    "historyDiff",
    "refreshHistory",
    "rollbackHistory",
    "terminalOutput",
    "terminalCommand",
    "runTerminalCommand",
    "fixItButton",
    "chatSelect",
    "executorSelect",
    "chatList",
    "messageStream",
    "taskTitle",
    "taskMeta",
    "taskSummary",
    "artifactList",
    "artifactDetail",
    "traceRail",
    "tracePayload",
    "composerContext",
    "taskPrompt",
    "toggleFileContext",
    "toggleSelectionContext",
    "toggleTerminalContext",
    "statusText",
    "runTaskButton",
    "newChatButton",
    "refreshExplorer",
    "deleteFile",
    "executorHealth",
    "fileCountStatus",
    "taskCountStatus",
    "chatCountStatus",
    "statusLeft",
    "statusBranchText",
    "statusPathText",
  ].forEach((id) => {
    els[id] = byId(id);
  });
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
  const value = text || "Ready.";
  els.statusText.textContent = value;
  els.statusLeft.textContent = value;
}

function trimText(value, limit = 120) {
  const clean = String(value || "").replace(/\s+/g, " ").trim();
  return clean.length <= limit ? clean : `${clean.slice(0, limit - 3)}...`;
}

function iconSvg(name) {
  const icons = {
    folder: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h6l2 2h8v10H4z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
    file: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4h7l4 4v12H7z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M14 4v4h4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
    code: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7L4 12l5 5M15 7l5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    markdown: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16v12H4zM7 15V9l3 3 3-3v6m3-6h2l-2 3 2 3h-2l-2-3z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
    config: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8.5A3.5 3.5 0 1112 15.5 3.5 3.5 0 0112 8.5zm8 3.5l-2.1.7a6.95 6.95 0 01-.6 1.4l1 2-1.9 1.9-2-.9a6.95 6.95 0 01-1.4.6L12 20l-1.1-2.3a6.95 6.95 0 01-1.4-.6l-2 .9-1.9-1.9 1-2a6.95 6.95 0 01-.6-1.4L4 12l2.1-.7a6.95 6.95 0 01.6-1.4l-1-2 1.9-1.9 2 .9a6.95 6.95 0 011.4-.6L12 4l1.1 2.3a6.95 6.95 0 011.4.6l2-.9 1.9 1.9-1 2c.27.44.47.91.6 1.4z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
  };
  return icons[name] || icons.file;
}

function iconForPath(path) {
  const lower = String(path || "").toLowerCase();
  if (lower.endsWith(".py") || lower.endsWith(".js") || lower.endsWith(".ts")) return "code";
  if (lower.endsWith(".md") || lower.endsWith(".txt")) return "markdown";
  if (lower.endsWith(".json") || lower.endsWith(".yaml") || lower.endsWith(".yml") || lower.endsWith(".toml") || lower.endsWith(".ini")) return "config";
  return "file";
}

function formatTimestamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  const hours = `${date.getHours()}`.padStart(2, "0");
  const minutes = `${date.getMinutes()}`.padStart(2, "0");
  return `${month}-${day} ${hours}:${minutes}`;
}

function countFiles(nodes) {
  let total = 0;
  (nodes || []).forEach((node) => {
    if (node.type === "file") {
      total += 1;
      return;
    }
    total += countFiles(node.children || []);
  });
  return total;
}

function currentTab() {
  return state.openTabs.find((tab) => tab.path === state.activePath) || null;
}

function ensureTab(path, content = "") {
  let tab = state.openTabs.find((row) => row.path === path);
  if (!tab) {
    tab = { path, original: content, content, history: [] };
    state.openTabs.push(tab);
  }
  return tab;
}

function getSelectionInfo() {
  const tab = currentTab();
  if (!tab) {
    return { text: "", chars: 0, lines: 0 };
  }
  const start = els.editorInput.selectionStart || 0;
  const end = els.editorInput.selectionEnd || 0;
  const text = tab.content.slice(start, end);
  return {
    text,
    chars: text.length,
    lines: text ? text.split("\n").length : 0,
  };
}

function selectionLabel() {
  const info = getSelectionInfo();
  if (!info.text.trim()) return "No selection";
  return `${info.lines || 1} line${info.lines === 1 ? "" : "s"}, ${info.chars} chars`;
}

function updateStatusPath() {
  els.statusPathText.textContent = state.activePath || "No file selected";
}

function scheduleRefreshDiff() {
  if (state.diffTimer) {
    clearTimeout(state.diffTimer);
  }
  state.diffTimer = setTimeout(() => {
    refreshDiff();
  }, 150);
}

function scheduleExplorerLoad() {
  if (state.explorerTimer) {
    clearTimeout(state.explorerTimer);
  }
  state.explorerTimer = setTimeout(() => {
    loadExplorer();
  }, 140);
}

function seedExpandedDirs(nodes, depth = 0) {
  (nodes || []).forEach((node) => {
    if (node.type === "dir" && depth < 2) {
      state.expandedDirs.add(node.path);
      seedExpandedDirs(node.children || [], depth + 1);
    }
  });
}

function renderChatList(chats) {
  els.chatList.innerHTML = "";
  if (!chats || !chats.length) {
    els.chatList.innerHTML = '<div class="empty-state">No chat threads yet.</div>';
    return;
  }

  const fragment = document.createDocumentFragment();
  chats.forEach((chat) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `thread-card ${chat.chat_id === state.activeChatId ? "active" : ""}`;
    card.innerHTML = `
      <div class="thread-card-header">
        <div class="thread-title"></div>
        <div class="thread-meta"></div>
      </div>
      <div class="thread-preview"></div>
    `;
    card.querySelector(".thread-title").textContent = trimText(chat.title || chat.chat_id, 36);
    card.querySelector(".thread-meta").textContent = `${chat.message_count || 0} msg`;
    card.querySelector(".thread-preview").textContent = chat.preview || "Open the thread to continue.";
    card.addEventListener("click", () => {
      loadChat(chat.chat_id);
      selectAssistantView("agent");
    });
    fragment.appendChild(card);
  });
  els.chatList.appendChild(fragment);
}

function renderBootstrap() {
  const boot = state.bootstrap;
  if (!boot) return;

  els.repoNameTop.textContent = boot.repo_name || "Repository";
  els.repoNameSide.textContent = boot.repo_name || "Repository";
  els.branchBadge.textContent = boot.git?.branch || "detached";
  els.modifiedBadge.textContent = `${(boot.git?.modified || []).length} modified`;
  els.statusBranchText.textContent = `Branch ${boot.git?.branch || "detached"}`;

  const fileCount = countFiles(state.treeRoots);
  els.fileCountStatus.textContent = `${fileCount} files`;
  els.taskCountStatus.textContent = `${(boot.tasks || []).length} tasks`;
  els.chatCountStatus.textContent = `${(boot.chats || []).length} chats`;

  const healthy = (boot.executors || []).filter((row) => row.ok).map((row) => row.name);
  els.executorHealth.textContent = healthy.length ? `${healthy.length} ready` : "offline";

  const previousExecutor = els.executorSelect.value;
  els.executorSelect.innerHTML = "";
  (boot.executors || []).forEach((row) => {
    const option = document.createElement("option");
    option.value = row.name;
    option.textContent = row.ok ? row.name : `${row.name} (offline)`;
    els.executorSelect.appendChild(option);
  });
  if (previousExecutor && (boot.executors || []).some((row) => row.name === previousExecutor)) {
    els.executorSelect.value = previousExecutor;
  }

  const previousChat = state.activeChatId;
  els.chatSelect.innerHTML = "";
  const blankOption = document.createElement("option");
  blankOption.value = "";
  blankOption.textContent = "New chat thread";
  els.chatSelect.appendChild(blankOption);

  (boot.chats || []).forEach((chat) => {
    const option = document.createElement("option");
    option.value = chat.chat_id;
    option.textContent = trimText(chat.title || chat.chat_id, 46);
    els.chatSelect.appendChild(option);
  });

  if (previousChat && (boot.chats || []).some((chat) => chat.chat_id === previousChat)) {
    state.activeChatId = previousChat;
  } else if (!state.activeChatId && boot.chats && boot.chats.length) {
    state.activeChatId = boot.chats[0].chat_id;
  }

  els.chatSelect.value = state.activeChatId || "";
  renderChatList(boot.chats || []);
}

async function loadBootstrap() {
  state.bootstrap = await fetchJson("/api/bootstrap");
  renderBootstrap();
}

function renderTree(nodes, host, depth = 0) {
  if (!host) return;
  host.innerHTML = "";
  if (!nodes || !nodes.length) {
    host.innerHTML = '<div class="empty-state">No files match the current filter.</div>';
    return;
  }

  const fragment = document.createDocumentFragment();
  nodes.forEach((node) => {
    const wrapper = document.createElement("div");
    wrapper.className = "tree-node";

    const row = document.createElement("div");
    row.className = `tree-row ${node.path === state.activePath ? "active" : ""}`;
    row.style.paddingLeft = `${8 + depth * 12}px`;

    const isDir = node.type === "dir";
    const expanded = state.expandedDirs.has(node.path);

    const caret = document.createElement("span");
    caret.className = "tree-caret";
    caret.textContent = isDir ? (expanded ? "v" : ">") : "";

    const icon = document.createElement("span");
    icon.className = `tree-icon ${isDir ? "dir" : "file"}`;
    icon.innerHTML = iconSvg(isDir ? "folder" : iconForPath(node.path));

    const name = document.createElement("span");
    name.className = "tree-name";
    name.textContent = node.name;

    row.appendChild(caret);
    row.appendChild(icon);
    row.appendChild(name);
    wrapper.appendChild(row);

    if (isDir) {
      row.addEventListener("click", () => {
        if (state.expandedDirs.has(node.path)) {
          state.expandedDirs.delete(node.path);
        } else {
          state.expandedDirs.add(node.path);
        }
        renderTree(state.treeRoots, els.fileTree);
      });
      if (expanded) {
        const children = document.createElement("div");
        children.className = "tree-children";
        renderTree(node.children || [], children, depth + 1);
        wrapper.appendChild(children);
      }
    } else {
      row.addEventListener("click", () => {
        openFile(node.path);
      });
    }

    fragment.appendChild(wrapper);
  });
  host.appendChild(fragment);
}

async function loadExplorer() {
  const query = encodeURIComponent((els.fileQuery.value || "").trim());
  const include = els.includeArchives.checked ? "1" : "0";
  const data = await fetchJson(`/api/explorer?include_archives=${include}&q=${query}`);
  state.treeRoots = data.tree || [];
  if (!state.explorerLoaded) {
    seedExpandedDirs(state.treeRoots);
    state.explorerLoaded = true;
  }
  renderTree(state.treeRoots, els.fileTree);
  els.fileCountStatus.textContent = `${data.count || 0} files`;
}
function renderTabs() {
  els.editorTabs.innerHTML = "";
  if (!state.openTabs.length) {
    return;
  }

  const fragment = document.createDocumentFragment();
  state.openTabs.forEach((tab) => {
    const dirty = tab.content !== tab.original;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `editor-tab ${tab.path === state.activePath ? "active" : ""} ${dirty ? "dirty" : ""}`;
    button.innerHTML = '<span class="tab-icon"></span><span class="name"></span><span class="close">x</span>';
    button.querySelector(".tab-icon").innerHTML = iconSvg(iconForPath(tab.path));
    button.querySelector(".name").textContent = tab.path.split("/").pop();
    button.addEventListener("click", (event) => {
      if (event.target.classList.contains("close")) {
        closeTab(tab.path);
        event.stopPropagation();
        return;
      }
      state.activePath = tab.path;
      renderEditor();
      renderTree(state.treeRoots, els.fileTree);
    });
    fragment.appendChild(button);
  });
  els.editorTabs.appendChild(fragment);
}

function updateLineNumbers(content) {
  const count = Math.max(1, String(content || "").split("\n").length);
  const lines = [];
  for (let index = 1; index <= count; index += 1) {
    lines.push(String(index));
  }
  els.lineNumbers.textContent = lines.join("\n");
}

function renderBreadcrumbs(path) {
  els.breadcrumbs.innerHTML = "";
  if (!path) {
    els.breadcrumbs.innerHTML = '<span class="breadcrumb-segment">No file selected</span>';
    return;
  }
  const fragment = document.createDocumentFragment();
  path.split("/").forEach((segment) => {
    const node = document.createElement("span");
    node.className = "breadcrumb-segment";
    node.textContent = segment;
    fragment.appendChild(node);
  });
  els.breadcrumbs.appendChild(fragment);
}

async function refreshDiff() {
  const tab = currentTab();
  if (!tab) {
    els.diffOutput.textContent = "Open a file to inspect its buffer diff.";
    return;
  }
  const payload = await fetchJson("/api/file/diff", {
    method: "POST",
    body: JSON.stringify({
      path: tab.path,
      before: tab.original,
      after: tab.content,
    }),
  });
  els.diffOutput.textContent = payload.diff || `No changes for ${tab.path}.`;
}

function renderHistory(tab) {
  els.historyList.innerHTML = "";
  if (!tab || !tab.history || !tab.history.length) {
    els.historyList.innerHTML = '<div class="empty-state">No patch history yet.</div>';
    els.historyDiff.textContent = "No patch history for the current file yet.";
    return;
  }

  const fragment = document.createDocumentFragment();
  tab.history.forEach((entry) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `history-item ${entry.id === state.activeHistoryId ? "active" : ""}`;
    item.textContent = `${entry.operation}  ${formatTimestamp(entry.timestamp)}`;
    item.addEventListener("click", () => {
      state.activeHistoryId = entry.id;
      renderHistory(tab);
      els.historyDiff.textContent = entry.diff || "No diff stored for this entry.";
    });
    fragment.appendChild(item);
  });
  els.historyList.appendChild(fragment);

  const active = tab.history.find((entry) => entry.id === state.activeHistoryId) || tab.history[0];
  state.activeHistoryId = active.id;
  els.historyDiff.textContent = active.diff || "No diff stored for this entry.";
}

function renderContextChips() {
  els.composerContext.innerHTML = "";

  const tab = currentTab();
  const selection = getSelectionInfo();
  const chips = [
    {
      key: "file",
      enabled: state.composerContext.file,
      available: Boolean(tab),
      text: tab ? `File: ${trimText(tab.path, 28)}` : "File: none",
    },
    {
      key: "selection",
      enabled: state.composerContext.selection,
      available: Boolean(selection.text.trim()),
      text: selection.text.trim() ? `Selection: ${selectionLabel()}` : "Selection: none",
    },
    {
      key: "terminal",
      enabled: state.composerContext.terminal,
      available: Boolean(state.terminalResult),
      text: state.terminalResult ? `Terminal: ${trimText(state.terminalResult.command || "recent run", 24)}` : "Terminal: idle",
    },
  ];

  const fragment = document.createDocumentFragment();
  chips.forEach((chip) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `context-chip ${chip.enabled ? "active" : ""} ${chip.available ? "warn" : ""}`;
    button.textContent = chip.text;
    button.title = chip.enabled ? "Click to exclude this context" : "Click to include this context";
    button.addEventListener("click", () => toggleContext(chip.key));
    fragment.appendChild(button);
  });
  els.composerContext.appendChild(fragment);

  els.toggleFileContext.textContent = state.composerContext.file ? "Active file on" : "Use active file";
  els.toggleSelectionContext.textContent = state.composerContext.selection ? "Selection on" : "Use selection";
  els.toggleTerminalContext.textContent = state.composerContext.terminal ? "Terminal on" : "Use terminal";
}

function renderEditor() {
  renderTabs();
  const tab = currentTab();

  if (!tab) {
    els.currentPath.textContent = "No file selected";
    els.editorStatusChip.textContent = "No buffer";
    els.editorInput.value = "";
    updateLineNumbers("");
    renderBreadcrumbs("");
    els.diffOutput.textContent = "Open a file to inspect its buffer diff.";
    els.historyList.innerHTML = '<div class="empty-state">No patch history yet.</div>';
    els.historyDiff.textContent = "No patch history for the current file yet.";
    updateStatusPath();
    renderContextChips();
    return;
  }

  els.currentPath.textContent = tab.path;
  els.editorInput.value = tab.content;
  els.editorStatusChip.textContent = tab.content === tab.original ? "Saved" : "Unsaved changes";
  updateLineNumbers(tab.content);
  renderBreadcrumbs(tab.path);
  renderHistory(tab);
  updateStatusPath();
  scheduleRefreshDiff();
  renderContextChips();
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
  renderTree(state.treeRoots, els.fileTree);
  setStatus(`Opened ${path}`);
}

function closeTab(path) {
  state.openTabs = state.openTabs.filter((tab) => tab.path !== path);
  if (state.activePath === path) {
    state.activePath = state.openTabs[0]?.path || "";
  }
  renderEditor();
  renderTree(state.treeRoots, els.fileTree);
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
  await loadBootstrap();
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
  await loadBootstrap();
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
  await loadBootstrap();
  setStatus(`Rolled back ${tab.path}`);
}

async function deleteCurrentFile() {
  const tab = currentTab();
  const path = tab?.path || state.activePath;
  if (!path) {
    setStatus("No file selected for deletion.");
    return;
  }
  const confirmed = window.confirm(`Delete file "${path}"?\nYou can restore it from Git if needed.`);
  if (!confirmed) return;

  const payload = await fetchJson("/api/file/delete", {
    method: "POST",
    body: JSON.stringify({ path, confirm: true }),
  });
  if (!payload.ok) {
    setStatus(payload.error || "Delete failed.");
    return;
  }
  state.openTabs = state.openTabs.filter((row) => row.path !== path);
  state.activePath = state.openTabs[0]?.path || "";
  renderEditor();
  await loadExplorer();
  await loadBootstrap();
  setStatus(`Deleted ${path}`);
}
function renderTerminal(result) {
  if (!result) {
    els.terminalOutput.textContent = "No terminal output yet. Run a safe repository command to get started.";
    els.fixItButton.disabled = true;
    renderContextChips();
    return;
  }

  const header = [`$ ${result.command || ""}`, `exit=${result.exit_code} duration=${result.duration_ms}ms`].join("\n");
  const body = [result.stdout, result.stderr].filter(Boolean).join("\n");
  els.terminalOutput.textContent = body ? `${header}\n\n${body}` : header;

  const errorLike = !result.ok || result.exit_code !== 0 || /error|traceback|failed|exception/i.test(body);
  els.fixItButton.disabled = !errorLike;
  renderContextChips();
  if (errorLike) {
    setStatus("Terminal command failed. You can send it to the agent with one click.");
  }
}

async function runTerminalCommand() {
  const command = (els.terminalCommand.value || "").trim();
  if (!command) {
    setStatus("Enter a terminal command first.");
    return;
  }
  const payload = await fetchJson("/api/terminal/run", {
    method: "POST",
    body: JSON.stringify({ command }),
  });
  state.terminalResult = payload;
  renderTerminal(payload);
  selectBottomPanel("terminal");
  setStatus(`Ran: ${command}`);
}

function prepareFixItTask() {
  if (!state.terminalResult) {
    setStatus("No terminal output to forward.");
    return;
  }
  state.composerContext.terminal = true;
  const output = els.terminalOutput.textContent || "";
  const snippet = output.length > 6000 ? `${output.slice(0, 6000)}\n...\n[truncated]` : output;
  els.taskPrompt.value = [
    "Diagnose the failing terminal command, make the needed repo changes, and explain how to verify the fix.",
    "",
    "Recent terminal output:",
    "```text",
    snippet,
    "```",
  ].join("\n");
  renderContextChips();
  selectAssistantView("agent");
  setStatus("Prepared a fix task from the terminal output.");
}

function renderMessages(messages) {
  els.messageStream.innerHTML = "";
  if (!messages || !messages.length) {
    els.messageStream.innerHTML = '<div class="empty-state">Start a chat or run a task to populate this thread.</div>';
    return;
  }

  const fragment = document.createDocumentFragment();
  messages.forEach((message) => {
    const card = document.createElement("div");
    card.className = `message ${message.role === "user" ? "user" : "assistant"}`;
    card.innerHTML = `
      <div class="message-role"></div>
      <div class="message-text"></div>
      <div class="message-footer">
        <span class="message-meta"></span>
        <button class="message-task ghost-btn small" type="button" style="display:none;">Open Task</button>
      </div>
    `;
    card.querySelector(".message-role").textContent = message.role;
    card.querySelector(".message-text").textContent = message.content || "";

    const metaBits = [formatTimestamp(message.created_at)];
    if (message.executor) metaBits.push(message.executor);
    if (message.status) metaBits.push(message.status);
    card.querySelector(".message-meta").textContent = metaBits.filter(Boolean).join("  ");

    const taskButton = card.querySelector(".message-task");
    if (message.task_id) {
      taskButton.style.display = "inline-flex";
      taskButton.textContent = `Task ${message.task_id}`;
      taskButton.addEventListener("click", () => {
        loadTask(message.task_id);
        selectAssistantView("task");
      });
    }
    fragment.appendChild(card);
  });
  els.messageStream.appendChild(fragment);
  els.messageStream.scrollTop = els.messageStream.scrollHeight;
}

async function loadChat(chatId) {
  if (!chatId) {
    state.activeChatId = "";
    renderMessages([]);
    renderChatList(state.bootstrap?.chats || []);
    els.chatSelect.value = "";
    return;
  }
  const payload = await fetchJson(`/api/chat/${encodeURIComponent(chatId)}`);
  state.activeChatId = chatId;
  els.chatSelect.value = chatId;
  renderMessages(payload.messages || []);
  renderChatList(state.bootstrap?.chats || []);
}

function renderArtifacts(artifacts) {
  els.artifactList.innerHTML = "";
  if (!artifacts || !artifacts.length) {
    els.artifactList.innerHTML = '<div class="empty-state">No artifacts for the selected task yet.</div>';
    els.artifactDetail.textContent = "No artifacts for the selected task yet.";
    return;
  }

  if (state.activeArtifactIndex < 0 || state.activeArtifactIndex >= artifacts.length) {
    state.activeArtifactIndex = 0;
  }

  const fragment = document.createDocumentFragment();
  artifacts.forEach((artifact, index) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `artifact-item ${index === state.activeArtifactIndex ? "active" : ""}`;
    row.textContent = trimText(`${artifact.kind || "artifact"} ${artifact.content || artifact.stdout || ""}`, 84);
    row.addEventListener("click", () => {
      state.activeArtifactIndex = index;
      renderArtifacts(artifacts);
    });
    fragment.appendChild(row);
  });
  els.artifactList.appendChild(fragment);

  const active = artifacts[state.activeArtifactIndex] || artifacts[0];
  els.artifactDetail.textContent = JSON.stringify(active, null, 2);
}

function renderTrace(events) {
  els.traceRail.innerHTML = "";
  if (!events || !events.length) {
    els.traceRail.innerHTML = '<div class="empty-state">No trace events yet.</div>';
    els.tracePayload.textContent = "No trace events yet.";
    return;
  }

  if (state.activeTraceIndex < 0 || state.activeTraceIndex >= events.length) {
    state.activeTraceIndex = 0;
  }

  const fragment = document.createDocumentFragment();
  events.forEach((event, index) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `trace-item ${index === state.activeTraceIndex ? "active" : ""}`;
    card.innerHTML = '<div class="trace-type"></div><div class="trace-meta"></div>';
    card.querySelector(".trace-type").textContent = event.event_type || "event";
    card.querySelector(".trace-meta").textContent = formatTimestamp(event.created_at);
    card.addEventListener("click", () => {
      state.activeTraceIndex = index;
      renderTrace(events);
    });
    fragment.appendChild(card);
  });
  els.traceRail.appendChild(fragment);

  const active = events[state.activeTraceIndex] || events[0];
  els.tracePayload.textContent = JSON.stringify(active, null, 2);
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
  els.taskMeta.textContent = live.running ? `running ${live.last_event || "working"}` : (task.status || live.status || "idle");
  els.taskSummary.textContent = payload.summary || task.summary || payload.checkpoint?.summary || "No summary yet.";
  renderArtifacts(payload.artifacts || []);
  renderTrace(payload.events || []);

  if (payload.checkpoint?.chat_id) {
    state.activeChatId = payload.checkpoint.chat_id;
    if (els.chatSelect.querySelector(`option[value="${payload.checkpoint.chat_id}"]`)) {
      els.chatSelect.value = payload.checkpoint.chat_id;
    }
    await loadChat(payload.checkpoint.chat_id);
  }
}
function composeTaskPrompt(userPrompt) {
  const blocks = [userPrompt.trim()];
  const tab = currentTab();
  const selection = getSelectionInfo();

  if (state.composerContext.file && tab) {
    const snapshot = tab.content.length > 3600 ? `${tab.content.slice(0, 3600)}\n...\n[truncated]` : tab.content;
    blocks.push([
      "Active file context:",
      `Path: ${tab.path}`,
      "```text",
      snapshot,
      "```",
    ].join("\n"));
  }

  if (state.composerContext.selection && selection.text.trim()) {
    const snippet = selection.text.length > 2200 ? `${selection.text.slice(0, 2200)}\n...\n[truncated]` : selection.text;
    blocks.push([
      "Selected editor range:",
      `Path: ${tab?.path || "current buffer"}`,
      "```text",
      snippet,
      "```",
    ].join("\n"));
  }

  if (state.composerContext.terminal && state.terminalResult) {
    const text = els.terminalOutput.textContent || "";
    const snippet = text.length > 4000 ? `${text.slice(0, 4000)}\n...\n[truncated]` : text;
    blocks.push([
      "Recent terminal session:",
      "```text",
      snippet,
      "```",
    ].join("\n"));
  }

  return blocks.filter(Boolean).join("\n\n");
}

async function runTask() {
  const goalInput = (els.taskPrompt.value || "").trim();
  if (!goalInput) {
    setStatus("Describe the repo task first.");
    return;
  }

  const payload = await fetchJson("/api/task/run", {
    method: "POST",
    body: JSON.stringify({
      goal: composeTaskPrompt(goalInput),
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

function toggleContext(key) {
  state.composerContext[key] = !state.composerContext[key];
  renderContextChips();
}

function selectBottomPanel(name) {
  state.bottomPanel = name;
  document.querySelectorAll(".bottom-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.panel === name);
  });
  document.querySelectorAll(".bottom-view").forEach((view) => {
    view.classList.toggle("active", view.dataset.panelView === name);
  });
}

function selectAssistantView(name) {
  state.assistantView = name;
  document.querySelectorAll(".assistant-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
  });
  document.querySelectorAll(".assistant-view").forEach((view) => {
    view.classList.toggle("active", view.dataset.viewPanel === name);
  });
}

function bindEvents() {
  els.refreshExplorer.addEventListener("click", loadExplorer);
  els.fileQuery.addEventListener("input", scheduleExplorerLoad);
  els.includeArchives.addEventListener("change", loadExplorer);

  els.saveFile.addEventListener("click", saveCurrentFile);
  els.reloadFile.addEventListener("click", reloadCurrentFile);
  els.deleteFile.addEventListener("click", deleteCurrentFile);

  els.editorInput.addEventListener("input", () => {
    const tab = currentTab();
    if (!tab) return;
    tab.content = els.editorInput.value;
    updateLineNumbers(tab.content);
    els.editorStatusChip.textContent = tab.content === tab.original ? "Saved" : "Unsaved changes";
    renderTabs();
    renderContextChips();
    scheduleRefreshDiff();
  });

  ["select", "keyup", "mouseup"].forEach((eventName) => {
    els.editorInput.addEventListener(eventName, () => {
      renderContextChips();
    });
  });

  els.editorInput.addEventListener("scroll", () => {
    els.lineNumbers.scrollTop = els.editorInput.scrollTop;
  });

  els.copySelectionToFind.addEventListener("click", () => {
    const start = els.editorInput.selectionStart || 0;
    const end = els.editorInput.selectionEnd || 0;
    els.findSnippet.value = els.editorInput.value.slice(start, end);
    selectBottomPanel("patch");
  });

  els.copySelectionToReplace.addEventListener("click", () => {
    const start = els.editorInput.selectionStart || 0;
    const end = els.editorInput.selectionEnd || 0;
    els.replaceSnippet.value = els.editorInput.value.slice(start, end);
    selectBottomPanel("patch");
  });

  els.applySnippet.addEventListener("click", applySnippetPatch);
  els.refreshHistory.addEventListener("click", () => openFile(state.activePath));
  els.rollbackHistory.addEventListener("click", rollbackHistory);

  els.runTerminalCommand.addEventListener("click", runTerminalCommand);
  els.fixItButton.addEventListener("click", prepareFixItTask);
  els.terminalCommand.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runTerminalCommand();
    }
  });

  els.chatSelect.addEventListener("change", () => {
    loadChat(els.chatSelect.value);
  });

  els.newChatButton.addEventListener("click", () => {
    state.activeChatId = "";
    els.chatSelect.value = "";
    renderMessages([]);
    renderChatList(state.bootstrap?.chats || []);
    setStatus("Started a new chat thread.");
  });

  els.toggleFileContext.addEventListener("click", () => toggleContext("file"));
  els.toggleSelectionContext.addEventListener("click", () => toggleContext("selection"));
  els.toggleTerminalContext.addEventListener("click", () => toggleContext("terminal"));
  els.runTaskButton.addEventListener("click", runTask);

  document.querySelectorAll(".bottom-tab").forEach((button) => {
    button.addEventListener("click", () => selectBottomPanel(button.dataset.panel));
  });
  document.querySelectorAll(".assistant-tab").forEach((button) => {
    button.addEventListener("click", () => selectAssistantView(button.dataset.view));
  });

  document.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === "s") {
      event.preventDefault();
      saveCurrentFile();
    }
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      runTask();
    }
  });
}

async function poll() {
  try {
    await loadBootstrap();
    if (state.activeChatId) {
      await loadChat(state.activeChatId);
    }
    if (state.activeTaskId) {
      await loadTask(state.activeTaskId);
    }
  } catch (error) {
    setStatus(error.message || String(error));
  }
}

async function boot() {
  initEls();
  bindEvents();
  renderEditor();
  renderTerminal(null);
  selectBottomPanel("changes");
  selectAssistantView("agent");

  await loadBootstrap();
  await loadExplorer();

  if (state.activeChatId) {
    await loadChat(state.activeChatId);
  }

  setStatus("Cursor-style workbench ready.");
  if (state.pollHandle) {
    clearInterval(state.pollHandle);
  }
  state.pollHandle = setInterval(poll, 2500);
}

document.addEventListener("DOMContentLoaded", boot);

