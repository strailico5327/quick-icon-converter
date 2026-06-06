"use strict";

const SIZE_OPTIONS = [16, 24, 32, 48, 64, 128, 256];
const DEFAULT_SIZES = new Set([16, 32, 48, 256]);
const SUPPORTED_TYPES = new Set(["image/png", "image/svg+xml"]);

const state = {
  items: [],
  running: false,
  nextId: 1,
};

const els = {
  dropZone: document.querySelector("#drop-zone"),
  fileInput: document.querySelector("#file-input"),
  sizeControls: document.querySelector("#size-controls"),
  allSizesButton: document.querySelector("#all-sizes-button"),
  convertButton: document.querySelector("#convert-button"),
  clearButton: document.querySelector("#clear-button"),
  statusText: document.querySelector("#status-text"),
  queueBody: document.querySelector("#queue-body"),
  queueSummary: document.querySelector("#queue-summary"),
  enableAll: document.querySelector("#enable-all"),
  emptyState: document.querySelector("#empty-state"),
  tableWrap: document.querySelector(".table-wrap"),
  previewCanvas: document.querySelector("#preview-canvas"),
  previewTitle: document.querySelector("#preview-title"),
  previewMeta: document.querySelector("#preview-meta"),
};

const crcTable = makeCrcTable();

init();

function init() {
  renderSizeControls();
  render();
  bindEvents();
  drawEmptyPreview();
}

function bindEvents() {
  els.fileInput.addEventListener("change", () => {
    addFiles(Array.from(els.fileInput.files || []));
    els.fileInput.value = "";
  });

  for (const eventName of ["dragenter", "dragover"]) {
    els.dropZone.addEventListener(eventName, event => {
      event.preventDefault();
      els.dropZone.classList.add("dragover");
    });
  }

  for (const eventName of ["dragleave", "drop"]) {
    els.dropZone.addEventListener(eventName, event => {
      event.preventDefault();
      els.dropZone.classList.remove("dragover");
    });
  }

  els.dropZone.addEventListener("drop", event => {
    addFiles(Array.from(event.dataTransfer?.files || []));
  });

  els.dropZone.addEventListener("keydown", event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      els.fileInput.click();
    }
  });

  els.sizeControls.addEventListener("change", event => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || !input.dataset.size || state.running) {
      return;
    }
    applySizeToSelected(Number(input.dataset.size), input.checked);
  });

  els.allSizesButton.addEventListener("click", toggleAllSizesForSelected);
  els.convertButton.addEventListener("click", startConversion);
  els.clearButton.addEventListener("click", clearQueue);

  els.enableAll.addEventListener("change", () => {
    if (state.running) {
      return;
    }
    for (const item of state.items) {
      item.enabled = els.enableAll.checked;
      if (item.enabled && item.sizes.size === 0) {
        item.sizes = new Set(DEFAULT_SIZES);
      }
    }
    setStatus(els.enableAll.checked ? "已启用全部文件" : "已停用全部文件");
    render();
  });

  els.queueBody.addEventListener("change", event => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || state.running) {
      return;
    }

    const item = itemFromElement(input);
    if (!item) {
      return;
    }

    if (input.classList.contains("row-select")) {
      item.selected = input.checked;
      render();
      updatePreview();
    }

    if (input.classList.contains("row-enabled")) {
      item.enabled = input.checked;
      if (item.enabled && item.sizes.size === 0) {
        item.sizes = new Set(DEFAULT_SIZES);
      }
      item.status = "Queued";
      render();
    }
  });

  els.queueBody.addEventListener("click", event => {
    const button = event.target.closest("button[data-action]");
    if (!button || state.running) {
      return;
    }

    const item = itemFromElement(button);
    if (!item) {
      return;
    }

    if (button.dataset.action === "delete") {
      removeItem(item.id);
    }
  });
}

function renderSizeControls() {
  els.sizeControls.innerHTML = SIZE_OPTIONS.map(size => {
    return `
      <label class="size-option">
        <input type="checkbox" data-size="${size}" />
        <span>${size}x</span>
      </label>
    `;
  }).join("");
}

function addFiles(files) {
  if (state.running) {
    setStatus("转换中不能修改队列");
    return;
  }

  const existing = new Set(state.items.map(item => `${item.file.name}:${item.file.size}:${item.file.lastModified}`));
  let added = 0;
  let skipped = 0;

  for (const file of files) {
    if (!isSupportedFile(file)) {
      skipped += 1;
      continue;
    }

    const key = `${file.name}:${file.size}:${file.lastModified}`;
    if (existing.has(key)) {
      skipped += 1;
      continue;
    }

    state.items.push({
      id: state.nextId++,
      file,
      enabled: true,
      selected: true,
      sizes: new Set(DEFAULT_SIZES),
      status: "Queued",
      remaining: DEFAULT_SIZES.size,
      message: "",
    });
    existing.add(key);
    added += 1;
  }

  if (added > 0) {
    const newestIds = new Set(state.items.slice(-added).map(item => item.id));
    for (const item of state.items) {
      item.selected = newestIds.has(item.id);
    }
  }

  setStatus(`已添加 ${added} 个文件${skipped ? `，跳过 ${skipped} 个` : ""}`);
  render();
  updatePreview();
}

function isSupportedFile(file) {
  const name = file.name.toLowerCase();
  return SUPPORTED_TYPES.has(file.type) || name.endsWith(".png") || name.endsWith(".svg");
}

function render() {
  const hasItems = state.items.length > 0;
  els.emptyState.classList.toggle("hidden", hasItems);
  els.tableWrap.classList.toggle("hidden", !hasItems);
  els.queueSummary.textContent = `${state.items.length} 个文件，${selectedItems().length} 个已选`;
  els.convertButton.disabled = state.running || buildJobs().length === 0;
  els.clearButton.disabled = state.running || !hasItems;
  els.enableAll.disabled = state.running || !hasItems;
  els.enableAll.checked = hasItems && state.items.every(item => item.enabled);
  els.enableAll.indeterminate = hasItems && state.items.some(item => item.enabled) && !els.enableAll.checked;

  els.queueBody.innerHTML = state.items.map(item => {
    const statusClass = statusClassFor(item);
    return `
      <tr data-id="${item.id}" class="${item.selected ? "selected" : ""} ${item.enabled ? "" : "disabled"}">
        <td class="center"><input class="row-select" type="checkbox" ${item.selected ? "checked" : ""} ${state.running ? "disabled" : ""} /></td>
        <td class="center"><input class="row-enabled" type="checkbox" ${item.enabled ? "checked" : ""} ${state.running ? "disabled" : ""} /></td>
        <td><span class="status-badge ${statusClass}" title="${escapeAttr(item.message)}">${statusText(item)}</span></td>
        <td class="center">${item.enabled ? item.remaining : 0}</td>
        <td class="sizes-cell">${sizeText(item.sizes)}</td>
        <td><div class="file-name" title="${escapeAttr(item.file.name)}">${escapeHtml(item.file.name)}</div></td>
        <td class="center">${fileFormat(item.file)}</td>
        <td class="center">${humanSize(item.file.size)}</td>
        <td class="center"><button class="row-button" type="button" data-action="delete" title="删除" ${state.running ? "disabled" : ""}>×</button></td>
      </tr>
    `;
  }).join("");

  syncSizeControls();
}

function syncSizeControls() {
  const selected = selectedItems();
  const enabled = selected.length > 0 && !state.running;
  const inputs = Array.from(els.sizeControls.querySelectorAll("input[data-size]"));

  for (const input of inputs) {
    const size = Number(input.dataset.size);
    input.disabled = !enabled;
    if (!enabled) {
      input.checked = false;
      input.indeterminate = false;
      continue;
    }

    const matches = selected.filter(item => item.sizes.has(size)).length;
    input.checked = matches === selected.length;
    input.indeterminate = matches > 0 && matches < selected.length;
  }

  els.allSizesButton.disabled = !enabled;
  els.allSizesButton.textContent =
    selected.length > 0 && selected.every(item => item.sizes.size === SIZE_OPTIONS.length)
      ? "清空尺寸"
      : "全选尺寸";
}

function applySizeToSelected(size, checked) {
  const selected = selectedItems();
  for (const item of selected) {
    if (checked) {
      item.sizes.add(size);
    } else {
      item.sizes.delete(size);
    }
    item.remaining = item.enabled ? item.sizes.size : 0;
    item.status = "Queued";
    item.message = "";
  }
  render();
}

function toggleAllSizesForSelected() {
  if (state.running) {
    return;
  }
  const selected = selectedItems();
  if (selected.length === 0) {
    return;
  }

  const allSelected = selected.every(item => item.sizes.size === SIZE_OPTIONS.length);
  for (const item of selected) {
    item.sizes = allSelected ? new Set() : new Set(SIZE_OPTIONS);
    item.remaining = item.enabled ? item.sizes.size : 0;
    item.status = "Queued";
    item.message = "";
  }
  render();
}

async function startConversion() {
  const jobs = buildJobs();
  if (jobs.length === 0 || state.running) {
    setStatus("请启用至少一个文件并选择尺寸");
    return;
  }

  state.running = true;
  setStatus("正在转换...");
  render();

  const outputs = [];
  const usedNames = new Set();
  let errorCount = 0;

  for (const item of state.items) {
    if (!item.enabled) {
      item.status = "Skipped";
      item.remaining = 0;
      item.message = "";
      continue;
    }
    if (item.sizes.size === 0) {
      item.status = "No sizes";
      item.remaining = 0;
      item.message = "";
      continue;
    }

    item.status = "Working";
    item.remaining = item.sizes.size;
    item.message = "";
    render();

    for (const size of Array.from(item.sizes).sort((a, b) => a - b)) {
      try {
        const icoBytes = await convertFileToIco(item.file, size);
        const outputName = uniqueOutputName(outputNameFor(item.file.name, size), usedNames);
        outputs.push({ name: outputName, bytes: icoBytes });
        item.remaining -= 1;
        item.status = item.remaining === 0 ? "Done" : "Working";
      } catch (error) {
        errorCount += 1;
        item.status = "Error";
        item.message = error instanceof Error ? error.message : "转换失败";
        item.remaining = 0;
        break;
      }
      render();
      await waitForFrame();
    }
  }

  try {
    if (outputs.length === 1) {
      downloadBlob(new Blob([outputs[0].bytes], { type: "image/x-icon" }), outputs[0].name);
    } else if (outputs.length > 1) {
      const zip = makeZip(outputs);
      downloadBlob(zip, "ico_converted.zip");
    }
  } finally {
    state.running = false;
    setStatus(
      outputs.length === 0
        ? "没有生成文件"
        : `已生成 ${outputs.length} 个 ICO${errorCount ? `，${errorCount} 个错误` : ""}`
    );
    render();
  }
}

function buildJobs() {
  return state.items.filter(item => item.enabled && item.sizes.size > 0);
}

async function convertFileToIco(file, size) {
  const image = await loadImage(file);
  const pngBytes = await drawImageToPng(image, size);
  revokeLoadedImage(image);
  return makeIco(pngBytes, size);
}

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      image.dataset.objectUrl = url;
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("图片无法读取"));
    };
    image.src = url;
  });
}

function revokeLoadedImage(image) {
  const url = image.dataset.objectUrl;
  if (url) {
    URL.revokeObjectURL(url);
  }
}

function drawImageToPng(image, size) {
  return new Promise((resolve, reject) => {
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      reject(new Error("当前浏览器不支持 Canvas"));
      return;
    }

    ctx.clearRect(0, 0, size, size);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";

    const sourceWidth = image.naturalWidth || size;
    const sourceHeight = image.naturalHeight || size;
    const scale = Math.min(size / sourceWidth, size / sourceHeight);
    const width = Math.max(1, Math.round(sourceWidth * scale));
    const height = Math.max(1, Math.round(sourceHeight * scale));
    const x = Math.floor((size - width) / 2);
    const y = Math.floor((size - height) / 2);
    ctx.drawImage(image, x, y, width, height);

    canvas.toBlob(blob => {
      if (!blob) {
        reject(new Error("PNG 数据生成失败"));
        return;
      }
      blob.arrayBuffer().then(buffer => resolve(new Uint8Array(buffer)), reject);
    }, "image/png");
  });
}

function makeIco(pngBytes, size) {
  const headerSize = 6 + 16;
  const bytes = new Uint8Array(headerSize + pngBytes.length);
  const view = new DataView(bytes.buffer);

  view.setUint16(0, 0, true);
  view.setUint16(2, 1, true);
  view.setUint16(4, 1, true);
  view.setUint8(6, size === 256 ? 0 : size);
  view.setUint8(7, size === 256 ? 0 : size);
  view.setUint8(8, 0);
  view.setUint8(9, 0);
  view.setUint16(10, 1, true);
  view.setUint16(12, 32, true);
  view.setUint32(14, pngBytes.length, true);
  view.setUint32(18, headerSize, true);
  bytes.set(pngBytes, headerSize);

  return bytes;
}

function makeZip(files) {
  const encoder = new TextEncoder();
  const localParts = [];
  const centralParts = [];
  let offset = 0;

  for (const file of files) {
    const nameBytes = encoder.encode(file.name);
    const crc = crc32(file.bytes);
    const { time, date } = dosDateTime(new Date());

    const local = new Uint8Array(30 + nameBytes.length);
    const localView = new DataView(local.buffer);
    localView.setUint32(0, 0x04034b50, true);
    localView.setUint16(4, 20, true);
    localView.setUint16(6, 0x0800, true);
    localView.setUint16(8, 0, true);
    localView.setUint16(10, time, true);
    localView.setUint16(12, date, true);
    localView.setUint32(14, crc, true);
    localView.setUint32(18, file.bytes.length, true);
    localView.setUint32(22, file.bytes.length, true);
    localView.setUint16(26, nameBytes.length, true);
    localView.setUint16(28, 0, true);
    local.set(nameBytes, 30);

    localParts.push(local, file.bytes);

    const central = new Uint8Array(46 + nameBytes.length);
    const centralView = new DataView(central.buffer);
    centralView.setUint32(0, 0x02014b50, true);
    centralView.setUint16(4, 20, true);
    centralView.setUint16(6, 20, true);
    centralView.setUint16(8, 0x0800, true);
    centralView.setUint16(10, 0, true);
    centralView.setUint16(12, time, true);
    centralView.setUint16(14, date, true);
    centralView.setUint32(16, crc, true);
    centralView.setUint32(20, file.bytes.length, true);
    centralView.setUint32(24, file.bytes.length, true);
    centralView.setUint16(28, nameBytes.length, true);
    centralView.setUint16(30, 0, true);
    centralView.setUint16(32, 0, true);
    centralView.setUint16(34, 0, true);
    centralView.setUint16(36, 0, true);
    centralView.setUint32(38, 0, true);
    centralView.setUint32(42, offset, true);
    central.set(nameBytes, 46);
    centralParts.push(central);

    offset += local.length + file.bytes.length;
  }

  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  endView.setUint32(0, 0x06054b50, true);
  endView.setUint16(4, 0, true);
  endView.setUint16(6, 0, true);
  endView.setUint16(8, files.length, true);
  endView.setUint16(10, files.length, true);
  endView.setUint32(12, centralSize, true);
  endView.setUint32(16, offset, true);
  endView.setUint16(20, 0, true);

  return new Blob([...localParts, ...centralParts, end], { type: "application/zip" });
}

function makeCrcTable() {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let c = i;
    for (let j = 0; j < 8; j += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[i] = c >>> 0;
  }
  return table;
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function dosDateTime(dateObject) {
  const year = Math.max(1980, dateObject.getFullYear());
  const month = dateObject.getMonth() + 1;
  const day = dateObject.getDate();
  const hours = dateObject.getHours();
  const minutes = dateObject.getMinutes();
  const seconds = Math.floor(dateObject.getSeconds() / 2);

  return {
    time: (hours << 11) | (minutes << 5) | seconds,
    date: ((year - 1980) << 9) | (month << 5) | day,
  };
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function updatePreview() {
  const item = selectedItems()[0] || state.items[0];
  if (!item) {
    drawEmptyPreview();
    return;
  }

  els.previewTitle.textContent = item.file.name;
  els.previewMeta.textContent = `${fileFormat(item.file)} · ${humanSize(item.file.size)}`;

  try {
    const image = await loadImage(item.file);
    const canvas = els.previewCanvas;
    const ctx = canvas.getContext("2d");
    const size = canvas.width;
    ctx.clearRect(0, 0, size, size);
    const sourceWidth = image.naturalWidth || size;
    const sourceHeight = image.naturalHeight || size;
    const scale = Math.min((size - 24) / sourceWidth, (size - 24) / sourceHeight);
    const width = Math.max(1, Math.round(sourceWidth * scale));
    const height = Math.max(1, Math.round(sourceHeight * scale));
    ctx.drawImage(image, Math.floor((size - width) / 2), Math.floor((size - height) / 2), width, height);
    revokeLoadedImage(image);
  } catch {
    drawEmptyPreview("无法预览");
  }
}

function drawEmptyPreview(text = "") {
  const canvas = els.previewCanvas;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!text) {
    els.previewTitle.textContent = "暂无预览";
    els.previewMeta.textContent = "添加文件后会显示第一项预览";
    return;
  }
  els.previewTitle.textContent = text;
  els.previewMeta.textContent = "这个文件仍可尝试转换";
}

function removeItem(id) {
  state.items = state.items.filter(item => item.id !== id);
  setStatus("已删除队列项");
  render();
  updatePreview();
}

function clearQueue() {
  if (state.running) {
    return;
  }
  state.items = [];
  setStatus("队列已清空");
  render();
  drawEmptyPreview();
}

function selectedItems() {
  return state.items.filter(item => item.selected);
}

function itemFromElement(element) {
  const row = element.closest("tr[data-id]");
  if (!row) {
    return null;
  }
  const id = Number(row.dataset.id);
  return state.items.find(item => item.id === id) || null;
}

function fileFormat(file) {
  return file.name.toLowerCase().endsWith(".svg") || file.type === "image/svg+xml" ? "SVG" : "PNG";
}

function statusText(item) {
  if (item.message) {
    return item.status;
  }
  if (item.status === "No sizes") {
    return "No sizes";
  }
  return item.status;
}

function statusClassFor(item) {
  if (item.status === "Done") {
    return "done";
  }
  if (item.status === "Error") {
    return "error";
  }
  if (item.status === "Skipped" || item.status === "No sizes") {
    return "skip";
  }
  return "";
}

function sizeText(sizes) {
  return sizes.size ? Array.from(sizes).sort((a, b) => a - b).map(size => `${size}x`).join(", ") : "-";
}

function outputNameFor(fileName, size) {
  const safe = fileName.replace(/[\\/:*?"<>|]+/g, "_");
  const stem = safe.replace(/\.[^.]+$/, "") || "icon";
  return `${stem}_${size}x.ico`;
}

function uniqueOutputName(name, usedNames) {
  if (!usedNames.has(name)) {
    usedNames.add(name);
    return name;
  }

  const dot = name.lastIndexOf(".");
  const stem = dot > -1 ? name.slice(0, dot) : name;
  const ext = dot > -1 ? name.slice(dot) : "";
  let counter = 2;
  let candidate = `${stem}-${counter}${ext}`;
  while (usedNames.has(candidate)) {
    counter += 1;
    candidate = `${stem}-${counter}${ext}`;
  }
  usedNames.add(candidate);
  return candidate;
}

function humanSize(byteCount) {
  let size = byteCount;
  const units = ["B", "KB", "MB", "GB"];
  for (const unit of units) {
    if (size < 1024 || unit === "GB") {
      return unit === "B" ? `${size} B` : `${size.toFixed(1)} ${unit}`;
    }
    size /= 1024;
  }
  return `${byteCount} B`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => {
    return {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char];
  });
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function setStatus(text) {
  els.statusText.textContent = text;
}

function waitForFrame() {
  return new Promise(resolve => requestAnimationFrame(() => resolve()));
}
