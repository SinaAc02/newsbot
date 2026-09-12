const setupView = document.querySelector("#setup-view");
const researchView = document.querySelector("#research-view");
const providerSelect = document.querySelector("#llm-provider");
const llmKeyRow = document.querySelector("#llm-key-row");

function showError(element, message = "") {
  element.textContent = message;
  element.classList.toggle("hidden", !message);
}

function appendInlineText(parent, text) {
  const pattern = /(\*\*[^*]+\*\*|\[\d+\])/g;
  let position = 0;
  for (const match of text.matchAll(pattern)) {
    parent.append(document.createTextNode(text.slice(position, match.index)));
    const value = match[0];
    if (value.startsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = value.slice(2, -2);
      parent.append(strong);
    } else {
      const citation = document.createElement("span");
      citation.className = "citation";
      citation.textContent = value;
      parent.append(citation);
    }
    position = match.index + value.length;
  }
  parent.append(document.createTextNode(text.slice(position)));
}

function renderReport(markdown) {
  const container = document.querySelector("#report-text");
  container.replaceChildren();
  let list = null;

  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      list = null;
      continue;
    }
    if (line.startsWith("## ")) {
      list = null;
      const heading = document.createElement("h2");
      heading.textContent = line.slice(3);
      container.append(heading);
      continue;
    }
    if (/^[-*] /.test(line)) {
      if (!list) {
        list = document.createElement("ul");
        container.append(list);
      }
      const item = document.createElement("li");
      appendInlineText(item, line.slice(2));
      list.append(item);
      continue;
    }
    list = null;
    const paragraph = document.createElement("p");
    appendInlineText(paragraph, line.replace(/^#+\s*/, ""));
    container.append(paragraph);
  }
}

function showSetup(status = {}) {
  researchView.classList.add("hidden");
  setupView.classList.remove("hidden");
  providerSelect.value = status.llm_provider || "ollama";
  document.querySelector("#llm-base-url").value = status.llm_base_url || "http://127.0.0.1:11434";
  document.querySelector("#llm-model").value = status.llm_model || "qwen3:8b";
  updateProviderFields();
}

function showResearch() {
  setupView.classList.add("hidden");
  researchView.classList.remove("hidden");
}

function updateProviderFields() {
  const cloud = providerSelect.value === "cloud";
  llmKeyRow.classList.toggle("hidden", !cloud);
  document.querySelector("#llm-api-key").required = cloud;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "Something went wrong");
  return payload;
}

async function streamResearch(payload, onEvent) {
  const response = await fetch("/api/research/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Research could not be started");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  while (true) {
    const { value, done } = await reader.read();
    pending += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = pending.split("\n");
    pending = lines.pop() || "";
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line));
    }
    if (done) break;
  }
}

async function loadStatus() {
  try {
    const status = await api("/api/status");
    status.configured ? showResearch() : showSetup(status);
  } catch (error) {
    showSetup();
    showError(document.querySelector("#setup-error"), error.message);
  }
}

providerSelect.addEventListener("change", () => {
  if (providerSelect.value === "ollama") {
    document.querySelector("#llm-base-url").value = "http://127.0.0.1:11434";
  } else {
    document.querySelector("#llm-base-url").value = "https://api.openai.com/v1";
  }
  updateProviderFields();
});

document.querySelector("#settings-button").addEventListener("click", async () => {
  const status = await api("/api/status");
  showSetup(status);
});

document.querySelector("#setup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const errorBox = document.querySelector("#setup-error");
  showError(errorBox);
  try {
    await api("/api/setup", {
      method: "POST",
      body: JSON.stringify({
        newsapi_key: document.querySelector("#newsapi-key").value,
        llm_provider: providerSelect.value,
        llm_base_url: document.querySelector("#llm-base-url").value,
        llm_model: document.querySelector("#llm-model").value,
        llm_api_key: document.querySelector("#llm-api-key").value,
      }),
    });
    document.querySelector("#newsapi-key").value = "";
    document.querySelector("#llm-api-key").value = "";
    showResearch();
  } catch (error) {
    showError(errorBox, error.message);
  }
});

document.querySelector("#research-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#research-button");
  const errorBox = document.querySelector("#research-error");
  const progressBox = document.querySelector("#progress-box");
  const progressList = document.querySelector("#progress-list");
  const originalText = button.textContent;
  showError(errorBox);
  progressList.replaceChildren();
  progressBox.classList.remove("hidden", "done");
  button.disabled = true;
  button.textContent = "Working…";
  try {
    let result = null;
    await streamResearch(
      {
        topic: document.querySelector("#topic").value,
        language: document.querySelector("#language").value,
        days: Number(document.querySelector("#days").value),
      },
      (event) => {
        if (event.type === "status") {
          const item = document.createElement("li");
          item.textContent = event.data;
          progressList.append(item);
          if (event.data === "Report complete.") progressBox.classList.add("done");
        } else if (event.type === "error") {
          throw new Error(event.data);
        } else if (event.type === "result") {
          result = event.data;
        }
      },
    );
    if (!result) throw new Error("The report finished without returning a result");
    document.querySelector("#empty-result").classList.add("hidden");
    document.querySelector("#report-result").classList.remove("hidden");
    document.querySelector("#result-panel").classList.remove("empty-state");
    document.querySelector("#report-topic").textContent = result.topic;
    renderReport(result.report);
    const sourceList = document.querySelector("#source-list");
    sourceList.replaceChildren();
    result.sources.forEach((source) => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = source.title;
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = source.source + (source.published_at ? ` · ${source.published_at}` : "");
      item.append(link, meta);
      sourceList.append(item);
    });
  } catch (error) {
    showError(errorBox, error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
});

loadStatus();
