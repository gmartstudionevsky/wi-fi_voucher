import { createClient } from "@supabase/supabase-js";

const SUPABASE_URL = "https://vsrletehzqlusmunvqji.supabase.co";
const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_EfAKLvfV--c-YdHMSVX9pw_T6P9RCbd";
const supabase = createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
    flowType: "pkce",
  },
});

const state = {
  session: null,
  hotel: null,
  membership: null,
  page: 1,
  pageSize: 25,
  items: [],
  stats: { available: 0, reserved: 0, used: 0, total: 0 },
  selected: new Set(),
  lastSelectedIndex: null,
  search: "",
  preview: null,
  editingId: null,
  connection: "online",
  pdfAssets: null,
};

const byId = (id) => document.getElementById(id);
const rowsElement = byId("passwordRows");
const workspace = byId("workspace");
const contextMenu = byId("contextMenu");
let toastTimer;
let searchTimer;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function showToast(message, type = "ok", duration = 3600) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.className = `toast visible${type === "error" ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.className = "toast"; }, duration);
}

function readableError(error) {
  if (!error) return "Неизвестная ошибка";
  const message = error.message || String(error);
  if (/Failed to fetch|NetworkError|fetch/i.test(message)) return "Нет связи с сервисом. Проверяем соединение…";
  if (/Invalid login credentials/i.test(message)) return "Неверная почта или пароль.";
  if (/Email not confirmed/i.test(message)) return "Подтвердите рабочую почту по ссылке из письма.";
  if (/rate limit/i.test(message)) return "Слишком много попыток. Подождите минуту и попробуйте снова.";
  return message;
}

function isTransient(error) {
  const value = `${error?.message || ""} ${error?.code || ""}`;
  return /fetch|network|timeout|502|503|504|PGRST000|PGRST001|PGRST002/i.test(value);
}

function setConnection(mode, text = "") {
  state.connection = mode;
  const banner = byId("connectionBanner");
  if (mode === "online") {
    banner.hidden = true;
    banner.classList.remove("error");
    return;
  }
  banner.hidden = false;
  banner.classList.toggle("error", mode === "error" || mode === "offline");
  byId("connectionText").textContent = text || (mode === "offline" ? "Нет подключения к интернету" : "Восстанавливаем соединение…");
}

async function rpc(name, args = {}, { retries = 2 } = {}) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    if (!navigator.onLine) {
      setConnection("offline");
      await sleep(350);
    }
    const { data, error } = await supabase.rpc(name, args);
    if (!error) {
      setConnection("online");
      return data;
    }
    lastError = error;
    if (!isTransient(error) || attempt === retries) break;
    setConnection("connecting", `Связь прервалась. Повторяем запрос ${attempt + 1} из ${retries}…`);
    await sleep(400 * (2 ** attempt) + Math.random() * 180);
  }
  if (isTransient(lastError)) setConnection("error", "Сервис временно недоступен. Данные не потеряны — повторите запрос.");
  throw new Error(readableError(lastError));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function can(...roles) {
  return roles.includes(state.membership?.role);
}

function renderStats(stats) {
  state.stats = stats;
  byId("availableStat").textContent = stats.available;
  byId("reservedStat").textContent = stats.reserved;
  byId("usedStat").textContent = stats.used;
}

function renderPermissions() {
  const operator = can("admin", "operator");
  byId("openImportButton").hidden = !operator;
  byId("pdfButton").hidden = !operator;
  byId("bulkIssueButton").hidden = !operator;
  byId("bulkDeleteButton").hidden = !can("admin");
  byId("contextIssueButton").hidden = !operator;
  byId("contextDeleteButton").hidden = !can("admin");
}

function renderRows() {
  if (!state.items.length) {
    rowsElement.innerHTML = `<tr><td class="empty" colspan="5">${state.search ? "По этому запросу ничего не найдено." : "Доступных паролей пока нет."}</td></tr>`;
  } else {
    const operator = can("admin", "operator");
    rowsElement.innerHTML = state.items.map((item, index) => {
      const selected = state.selected.has(item.id);
      const number = (state.page - 1) * state.pageSize + index + 1;
      const password = state.editingId === item.id
        ? `<input class="edit-password" data-edit-id="${item.id}" value="${escapeHtml(item.password)}" maxlength="256" aria-label="Редактировать пароль">`
        : `<span class="password-cell" data-password-id="${item.id}" title="Двойной клик — изменить">${escapeHtml(item.password)}</span>`;
      return `<tr data-id="${item.id}" class="${selected ? "selected" : ""}">
        <td class="col-check"><input class="row-check" type="checkbox" data-index="${index}" data-id="${item.id}" ${selected ? "checked" : ""} aria-label="Выбрать ${escapeHtml(item.password)}"></td>
        <td class="col-number">${number}</td><td>${password}</td>
        <td class="col-date">${escapeHtml(formatDate(item.created_at))}</td>
        <td class="col-actions"><div class="row-actions">
          ${operator ? `<button class="text-action issue-one" type="button" data-id="${item.id}">Скопировать и выдать</button><button class="text-action muted edit-one" type="button" data-id="${item.id}">Изменить</button>` : `<span class="filter-note">Только просмотр</span>`}
        </div></td></tr>`;
    }).join("");
  }
  syncSelectionUi();
  if (state.editingId !== null) {
    const input = rowsElement.querySelector(`[data-edit-id="${state.editingId}"]`);
    input?.focus();
    input?.select();
  }
}

function syncSelectionUi() {
  const count = state.selected.size;
  byId("bulkbar").classList.toggle("visible", count > 0);
  byId("selectionCount").textContent = `Выбрано: ${count}`;
  const ids = state.items.map((item) => item.id);
  const selected = ids.filter((id) => state.selected.has(id)).length;
  byId("selectAll").checked = ids.length > 0 && selected === ids.length;
  byId("selectAll").indeterminate = selected > 0 && selected < ids.length;
}

async function refreshPasswords({ preserveSelection = false } = {}) {
  if (!state.hotel) return;
  const offset = (state.page - 1) * state.pageSize;
  const data = await rpc("voucher_list", {
    p_hotel_id: state.hotel.id,
    p_limit: state.pageSize,
    p_offset: offset,
    p_search: state.search,
  });
  state.items = data.items || [];
  if (!preserveSelection) state.selected.clear();
  renderStats(data.stats);
  renderRows();
  const start = state.items.length ? offset + 1 : 0;
  const end = offset + state.items.length;
  byId("rangeLabel").textContent = `${start}–${end} из ${data.stats.available}`;
  byId("pageLabel").textContent = state.page;
  byId("prevPage").disabled = state.page === 1;
  byId("nextPage").disabled = end >= data.stats.available || !state.items.length;
}

async function bootstrapApp(session) {
  state.session = session;
  byId("authScreen").hidden = true;
  byId("appScreen").hidden = false;
  try {
    const data = await rpc("voucher_bootstrap", {}, { retries: 3 });
    state.hotel = data.hotel;
    state.membership = data.membership;
    byId("hotelName").textContent = data.hotel.name.toUpperCase();
    byId("accountEmail").textContent = data.membership.email || session.user.email;
    byId("accountName").textContent = data.membership.display_name || "Профиль";
    byId("accountRole").textContent = ({ admin: "Администратор", operator: "Оператор", viewer: "Просмотр" })[data.membership.role] || data.membership.role;
    renderStats(data.stats);
    renderPermissions();
    await refreshPasswords();
  } catch (error) {
    if (/не выдан доступ|Нет доступа/i.test(error.message)) {
      await supabase.auth.signOut();
      showLogin("Вход выполнен, но этой почте ещё не выдан доступ. Обратитесь к администратору.", true);
      return;
    }
    showToast(error.message, "error", 6000);
  }
}

function showLogin(message = "", error = false) {
  state.session = null;
  state.hotel = null;
  state.membership = null;
  byId("appScreen").hidden = true;
  byId("authScreen").hidden = false;
  const status = byId("authStatus");
  status.textContent = message;
  status.classList.toggle("error", error);
}

async function handleLogin(event) {
  event.preventDefault();
  const email = byId("emailInput").value.trim().toLowerCase();
  const password = byId("passwordInputAuth").value;
  if (!email || !password) {
    showLogin("Введите рабочую почту и пароль либо используйте ссылку для входа.", true);
    return;
  }
  const button = byId("signInButton");
  button.disabled = true;
  try {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
  } catch (error) {
    showLogin(readableError(error), true);
  } finally {
    button.disabled = false;
  }
}

async function sendMagicLink() {
  const email = byId("emailInput").value.trim().toLowerCase();
  if (!email) {
    showLogin("Введите рабочую почту, на которую отправить ссылку.", true);
    byId("emailInput").focus();
    return;
  }
  const button = byId("magicLinkButton");
  button.disabled = true;
  try {
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: window.location.origin, shouldCreateUser: true },
    });
    if (error) throw error;
    showLogin(`Ссылка отправлена на ${email}. Откройте письмо на этом устройстве.`, false);
  } catch (error) {
    showLogin(readableError(error), true);
  } finally {
    button.disabled = false;
  }
}

function selectedItems() {
  return state.items.filter((item) => state.selected.has(item.id));
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.cssText = "position:fixed;opacity:0";
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

async function copySelectedWithoutIssue() {
  const items = selectedItems();
  if (!items.length) return;
  await copyText(items.map((item) => item.password).join("\n"));
  showToast(`Скопировано без изменения статуса: ${items.length}`);
  hideContextMenu();
}

async function issueIds(ids) {
  if (!ids.length) return;
  const data = await rpc("voucher_issue", { p_hotel_id: state.hotel.id, p_ids: ids });
  await copyText(data.passwords.join("\n"));
  state.selected.clear();
  renderStats(data.stats);
  await refreshPasswords();
  showToast(`Скопировано и отмечено использованными: ${data.issued}`);
  hideContextMenu();
}

async function deleteIds(ids) {
  if (!ids.length || !can("admin")) return;
  if (!window.confirm(`Удалить доступные пароли: ${ids.length}? Это действие нельзя отменить.`)) return;
  const data = await rpc("voucher_delete", { p_hotel_id: state.hotel.id, p_ids: ids });
  state.selected.clear();
  renderStats(data.stats);
  await refreshPasswords();
  showToast(`Удалено: ${data.deleted}`);
  hideContextMenu();
}

function beginEdit(id) {
  if (!can("admin", "operator")) return;
  state.editingId = id;
  renderRows();
}

async function finishEdit(input, save) {
  const id = Number(input.dataset.editId);
  const original = state.items.find((item) => item.id === id);
  if (!save || !original) {
    state.editingId = null;
    renderRows();
    return;
  }
  const value = input.value.trim();
  if (!value || value === original.password) {
    state.editingId = null;
    renderRows();
    return;
  }
  await rpc("voucher_update", { p_hotel_id: state.hotel.id, p_id: id, p_password: value });
  state.editingId = null;
  await refreshPasswords();
  showToast("Пароль обновлён");
}

function setSelected(id, checked, index, range) {
  if (range && state.lastSelectedIndex !== null) {
    const start = Math.min(index, state.lastSelectedIndex);
    const end = Math.max(index, state.lastSelectedIndex);
    for (let i = start; i <= end; i += 1) {
      const item = state.items[i];
      if (item) checked ? state.selected.add(item.id) : state.selected.delete(item.id);
    }
  } else {
    checked ? state.selected.add(id) : state.selected.delete(id);
  }
  state.lastSelectedIndex = index;
  renderRows();
}

function showContextMenu(event) {
  if (!state.selected.size) return;
  event.preventDefault();
  const width = 295;
  contextMenu.style.left = `${Math.max(12, Math.min(event.clientX, window.innerWidth - width - 12))}px`;
  contextMenu.style.top = `${Math.max(12, Math.min(event.clientY, window.innerHeight - 190))}px`;
  contextMenu.classList.add("visible");
}

function hideContextMenu() { contextMenu.classList.remove("visible"); }

function parseInput(text) {
  return text.replace(/\r/g, "\n").split(/[\n\t,; ]+/).map((value) => value.trim()).filter(Boolean).slice(0, 5000);
}

async function previewImport() {
  const passwords = parseInput(byId("passwordInput").value);
  if (!passwords.length) throw new Error("Вставьте пароли или загрузите файл");
  const button = byId("previewImportButton");
  button.disabled = true;
  try {
    state.preview = await rpc("voucher_import_preview", { p_hotel_id: state.hotel.id, p_passwords: passwords });
    renderImportPreview();
  } finally {
    button.disabled = false;
  }
}

function renderImportPreview() {
  const { summary, items } = state.preview;
  byId("recognizedCount").textContent = summary.recognized;
  byId("newCount").textContent = summary.new;
  byId("duplicateCount").textContent = summary.duplicates;
  byId("invalidCount").textContent = summary.invalid;
  byId("importPreview").classList.add("visible");
  byId("commitImportButton").disabled = summary.new === 0;
  byId("commitImportButton").textContent = `Добавить ${summary.new} новых`;
  const notable = items.filter((item) => item.status !== "new").slice(0, 20);
  byId("previewList").innerHTML = notable.length
    ? notable.map((item) => `<div class="preview-row"><code>${escapeHtml(item.normalized || item.value || "пустая строка")}</code><span class="status-${item.status}">${escapeHtml(item.reason || item.status)}</span></div>`).join("")
    : `<div class="preview-row"><span>Все значения готовы к добавлению.</span><span class="status-new">Новые</span></div>`;
}

function invalidateImportPreview() {
  state.preview = null;
  byId("importPreview").classList.remove("visible");
  byId("commitImportButton").disabled = true;
  byId("commitImportButton").textContent = "Сначала проверить пароли";
}

async function commitImport() {
  if (!state.preview) return;
  const passwords = state.preview.items.filter((item) => item.status === "new").map((item) => item.normalized);
  if (!passwords.length) return;
  const button = byId("commitImportButton");
  button.disabled = true;
  try {
    const data = await rpc("voucher_import", { p_hotel_id: state.hotel.id, p_passwords: passwords });
    renderStats(data.stats);
    closeImport();
    state.page = 1;
    await refreshPasswords();
    showToast(`Добавлено: ${data.added}. Дубликаты не загружены: ${data.duplicates}.`);
  } finally {
    button.disabled = false;
  }
}

function openImport() {
  workspace.classList.add("drawer-open");
  document.querySelector(".topbar").inert = true;
  document.querySelector(".main").inert = true;
  setTimeout(() => byId("passwordInput").focus(), 60);
}

function closeImport() {
  workspace.classList.remove("drawer-open");
  document.querySelector(".topbar").inert = false;
  document.querySelector(".main").inert = false;
  byId("passwordInput").value = "";
  byId("fileInput").value = "";
  invalidateImportPreview();
}

function setImportTab(tab) {
  const fileMode = tab === "file";
  byId("pasteTab").classList.toggle("active", !fileMode);
  byId("fileTab").classList.toggle("active", fileMode);
  byId("pasteTab").setAttribute("aria-selected", String(!fileMode));
  byId("fileTab").setAttribute("aria-selected", String(fileMode));
  byId("passwordInput").style.display = fileMode ? "none" : "block";
  byId("dropzone").classList.toggle("active", fileMode);
}

async function loadFile(file) {
  if (!file) return;
  if (file.size > 2_000_000) throw new Error("Файл больше 2 МБ");
  byId("passwordInput").value = await file.text();
  setImportTab("paste");
  await previewImport();
}

async function loadPdfAssets() {
  if (state.pdfAssets) return state.pdfAssets;
  const [layoutResponse, ruResponse, enResponse, fontResponse] = await Promise.all([
    fetch("/templates/layout.json"),
    fetch("/templates/brochure_ru.pdf"),
    fetch("/templates/brochure_en.pdf"),
    fetch("/fonts/circe.ttf"),
  ]);
  if (![layoutResponse, ruResponse, enResponse, fontResponse].every((response) => response.ok)) throw new Error("Не удалось загрузить шаблоны PDF.");
  state.pdfAssets = {
    layout: await layoutResponse.json(),
    ru: await ruResponse.arrayBuffer(),
    en: await enResponse.arrayBuffer(),
    font: await fontResponse.arrayBuffer(),
  };
  return state.pdfAssets;
}

async function createVoucherPdf(passwords, ruCount, progress) {
  const [assets, module] = await Promise.all([loadPdfAssets(), import("./pdf.js")]);
  return module.createVoucherPdf({ passwords, ruCount, assets, progress });
}

function downloadBlob(bytes) {
  const blob = new Blob([bytes], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `wifi-vouchers-${new Date().toISOString().replace(/[:.]/g, "-")}.pdf`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

async function generatePdf() {
  const ru = Number(byId("ruCount").value || 0);
  const en = Number(byId("enCount").value || 0);
  if (!Number.isInteger(ru) || !Number.isInteger(en) || ru < 0 || en < 0 || ru + en < 1 || ru + en > 500) throw new Error("Укажите от 1 до 500 брошюр.");
  const button = byId("generateButton");
  const status = byId("generationStatus");
  const title = byId("generationStatusTitle");
  const detail = byId("generationStatusDetail");
  const bar = byId("generationProgress");
  const controls = [button, byId("closePdfButton"), byId("cancelPdfButton")];
  let reservation;
  controls.forEach((control) => { control.disabled = true; });
  status.hidden = false;
  bar.value = 2;
  title.textContent = `Готовим ${ru + en} карточек`;
  detail.textContent = "Резервируем пароли…";
  try {
    reservation = await rpc("voucher_reserve", { p_hotel_id: state.hotel.id, p_ru: ru, p_en: en });
    const bytes = await createVoucherPdf(reservation.passwords, ru, (done, total) => {
      bar.value = 8 + Math.round((done / total) * 82);
      detail.textContent = `Собрано ${done} из ${total}`;
    });
    detail.textContent = "Подтверждаем выдачу…";
    bar.value = 94;
    const committed = await rpc("voucher_generation_commit", { p_hotel_id: state.hotel.id, p_batch_id: reservation.batch_id }, { retries: 3 });
    reservation = null;
    renderStats(committed.stats);
    bar.value = 100;
    downloadBlob(bytes);
    byId("pdfDialog").close();
    await refreshPasswords();
    showToast(`PDF готов и скачан: ${ru + en} карточек`);
  } catch (error) {
    if (reservation?.batch_id) {
      try {
        await rpc("voucher_generation_release", { p_hotel_id: state.hotel.id, p_batch_id: reservation.batch_id, p_error: error.message }, { retries: 3 });
      } catch (releaseError) {
        console.error("Could not release reservation", releaseError);
      }
    }
    throw error;
  } finally {
    controls.forEach((control) => { control.disabled = false; });
    status.hidden = true;
    bar.value = 0;
  }
}

function bindEvents() {
  byId("loginForm").addEventListener("submit", handleLogin);
  byId("magicLinkButton").addEventListener("click", sendMagicLink);
  byId("signOutButton").addEventListener("click", async () => { await supabase.auth.signOut(); showLogin("Вы вышли из сервиса."); });
  byId("accountButton").addEventListener("click", () => {
    const menu = byId("accountMenu");
    menu.hidden = !menu.hidden;
    byId("accountButton").setAttribute("aria-expanded", String(!menu.hidden));
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest("#accountButton,#accountMenu")) byId("accountMenu").hidden = true;
    if (!event.target.closest("#contextMenu")) hideContextMenu();
  });
  window.addEventListener("offline", () => setConnection("offline"));
  window.addEventListener("online", () => { setConnection("connecting"); refreshPasswords().catch((error) => showToast(error.message, "error")); });
  byId("retryButton").addEventListener("click", () => refreshPasswords().catch((error) => showToast(error.message, "error")));
  byId("refreshButton").addEventListener("click", () => refreshPasswords({ preserveSelection: true }).catch((error) => showToast(error.message, "error")));

  rowsElement.addEventListener("change", (event) => {
    const checkbox = event.target.closest(".row-check");
    if (checkbox) setSelected(Number(checkbox.dataset.id), checkbox.checked, Number(checkbox.dataset.index), event.shiftKey);
  });
  rowsElement.addEventListener("click", async (event) => {
    const issue = event.target.closest(".issue-one");
    const edit = event.target.closest(".edit-one");
    try {
      if (issue) await issueIds([Number(issue.dataset.id)]);
      else if (edit) beginEdit(Number(edit.dataset.id));
    } catch (error) { showToast(error.message, "error"); }
  });
  rowsElement.addEventListener("dblclick", (event) => {
    const cell = event.target.closest(".password-cell");
    if (cell) beginEdit(Number(cell.dataset.passwordId));
  });
  rowsElement.addEventListener("keydown", async (event) => {
    const input = event.target.closest(".edit-password");
    if (!input) return;
    if (event.key === "Enter") { event.preventDefault(); try { await finishEdit(input, true); } catch (error) { showToast(error.message, "error"); } }
    else if (event.key === "Escape") finishEdit(input, false);
  });
  rowsElement.addEventListener("focusout", async (event) => {
    const input = event.target.closest(".edit-password");
    if (!input || event.relatedTarget?.closest(".edit-password")) return;
    try { await finishEdit(input, true); } catch (error) { showToast(error.message, "error"); }
  });
  byId("passwordGrid").addEventListener("contextmenu", showContextMenu);
  document.addEventListener("keydown", async (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c" && state.selected.size && !event.target.matches("input,textarea")) {
      event.preventDefault(); await copySelectedWithoutIssue();
    }
    if (event.key === "Escape") { hideContextMenu(); if (workspace.classList.contains("drawer-open")) closeImport(); }
  });
  byId("selectAll").addEventListener("change", (event) => { state.items.forEach((item) => event.target.checked ? state.selected.add(item.id) : state.selected.delete(item.id)); renderRows(); });
  byId("bulkIssueButton").addEventListener("click", () => issueIds([...state.selected]).catch((error) => showToast(error.message, "error")));
  byId("bulkDeleteButton").addEventListener("click", () => deleteIds([...state.selected]).catch((error) => showToast(error.message, "error")));
  byId("clearSelectionButton").addEventListener("click", () => { state.selected.clear(); renderRows(); });
  byId("contextIssueButton").addEventListener("click", () => issueIds([...state.selected]).catch((error) => showToast(error.message, "error")));
  byId("contextCopyButton").addEventListener("click", copySelectedWithoutIssue);
  byId("contextDeleteButton").addEventListener("click", () => deleteIds([...state.selected]).catch((error) => showToast(error.message, "error")));
  byId("searchInput").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.search = event.target.value.trim(); state.page = 1; refreshPasswords().catch((error) => showToast(error.message, "error")); }, 250);
  });
  byId("prevPage").addEventListener("click", () => { if (state.page > 1) { state.page -= 1; refreshPasswords().catch((error) => showToast(error.message, "error")); } });
  byId("nextPage").addEventListener("click", () => { state.page += 1; refreshPasswords().catch((error) => showToast(error.message, "error")); });

  byId("openImportButton").addEventListener("click", openImport);
  ["closeImportButton", "importBackdrop", "cancelImportButton"].forEach((id) => byId(id).addEventListener("click", closeImport));
  byId("pasteTab").addEventListener("click", () => setImportTab("paste"));
  byId("fileTab").addEventListener("click", () => setImportTab("file"));
  byId("previewImportButton").addEventListener("click", () => previewImport().catch((error) => showToast(error.message, "error")));
  byId("clearImportButton").addEventListener("click", () => { byId("passwordInput").value = ""; byId("fileInput").value = ""; invalidateImportPreview(); });
  byId("passwordInput").addEventListener("input", invalidateImportPreview);
  byId("commitImportButton").addEventListener("click", () => commitImport().catch((error) => showToast(error.message, "error")));
  byId("fileInput").addEventListener("change", (event) => loadFile(event.target.files[0]).catch((error) => showToast(error.message, "error")));
  const dropzone = byId("dropzone");
  ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.remove("dragover"); }));
  dropzone.addEventListener("drop", (event) => loadFile(event.dataTransfer.files[0]).catch((error) => showToast(error.message, "error")));

  byId("pdfButton").addEventListener("click", () => byId("pdfDialog").showModal());
  ["closePdfButton", "cancelPdfButton"].forEach((id) => byId(id).addEventListener("click", () => byId("pdfDialog").close()));
  byId("generateButton").addEventListener("click", () => generatePdf().catch((error) => showToast(error.message, "error", 6000)));
}

async function initialize() {
  bindEvents();
  const { data, error } = await supabase.auth.getSession();
  if (error) showLogin(readableError(error), true);
  else if (data.session) await bootstrapApp(data.session);
  else showLogin();

  supabase.auth.onAuthStateChange((event, session) => {
    if (event === "SIGNED_OUT" || !session) showLogin();
    else if (session?.access_token !== state.session?.access_token) setTimeout(() => bootstrapApp(session), 0);
  });
}

initialize().catch((error) => showLogin(readableError(error), true));
