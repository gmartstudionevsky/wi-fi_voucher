const CONFIG = Object.freeze({
  VERSION: '2026-05-21-unified-reservations',
  SPREADSHEET_ID: '127zHlLiojIdj60UJ42vgIU1SlCftqyB-15C9Ur26YL0',
  PASSWORDS_SHEET: 'Пароли',
  REQUESTS_SHEET: 'запрошено через QR-код',
  FIRST_DATA_ROW: 2,
  VOUCHER_COLUMN: 1,
  ARCHIVE_VOUCHERS_COLUMN: 4,
  DEVICES_PER_VOUCHER: 5,
  MAX_DEVICES: 20,
  MAX_FIO_LENGTH: 120,
  MAX_APARTMENT: 999,
  MAX_RESERVATION_COUNT: 500,
  LAST_RESERVED_ROW_PROPERTY: 'LAST_RESERVED_ROW'
});

function doPost(e) {
  const lock = LockService.getScriptLock();

  if (!lock.tryLock(30000)) {
    return jsonOut({ error: 'Busy' });
  }

  try {
    const data = parseRequest(e);
    const mode = normalizeText(data.mode || data.action);

    if (mode === 'reserve' || data.voucher_count) {
      return handleReservationRequest(data);
    }

    return handleGuestRequest(data);
  } catch (error) {
    console.error('Error in doPost:', error);
    return jsonOut({ error: error && error.publicMessage ? error.publicMessage : 'Internal error' });
  } finally {
    try {
      lock.releaseLock();
    } catch (error) {
      console.warn('Could not release lock:', error);
    }
  }
}

function doGet() {
  return jsonOut({ status: 'ok', version: CONFIG.VERSION });
}

function doOptions() {
  return ContentService
    .createTextOutput('')
    .setMimeType(ContentService.MimeType.TEXT);
}

function handleGuestRequest(data) {
  const fio = normalizeText(data.fio);
  const apartment = normalizeText(data.apartment);
  const numDevices = Number.parseInt(data.num_devices, 10);
  const language = data.language === 'en' ? 'en' : 'ru';

  if (!isValidGuestRequest(fio, apartment, numDevices)) {
    return jsonOut({ error: 'Bad request' });
  }

  const spreadsheet = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  const passwordsSheet = getRequiredSheet(spreadsheet, CONFIG.PASSWORDS_SHEET);
  const requestsSheet = getRequiredSheet(spreadsheet, CONFIG.REQUESTS_SHEET);
  const voucherCount = Math.ceil(numDevices / CONFIG.DEVICES_PER_VOUCHER);
  const reservation = reserveVouchers(passwordsSheet, requestsSheet, voucherCount);

  appendArchiveRow(requestsSheet, fio, apartment, reservation.vouchers);
  rememberLastReservedRow(reservation.lastReservedRow);

  return jsonOut({ vouchers: reservation.vouchers, language });
}

function handleReservationRequest(data) {
  const voucherCount = Number.parseInt(data.voucher_count, 10);
  if (!Number.isInteger(voucherCount) || voucherCount < 1 || voucherCount > CONFIG.MAX_RESERVATION_COUNT) {
    return jsonOut({ error: 'Bad reservation count' });
  }

  const spreadsheet = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  const passwordsSheet = getRequiredSheet(spreadsheet, CONFIG.PASSWORDS_SHEET);
  const requestsSheet = getRequiredSheet(spreadsheet, CONFIG.REQUESTS_SHEET);
  const reservation = reserveVouchers(passwordsSheet, requestsSheet, voucherCount);

  const source = normalizeText(data.source) || 'reservation';
  const details = buildReservationDetails(data);
  appendArchiveRow(requestsSheet, source, details, reservation.vouchers);
  rememberLastReservedRow(reservation.lastReservedRow);

  return jsonOut({ vouchers: reservation.vouchers, source, version: CONFIG.VERSION });
}

function parseRequest(e) {
  const contents = e && e.postData && e.postData.contents ? e.postData.contents : '{}';
  try {
    return JSON.parse(contents);
  } catch (error) {
    return {};
  }
}

function normalizeText(value) {
  return String(value || '').trim().replace(/\s+/g, ' ');
}

function isValidGuestRequest(fio, apartment, numDevices) {
  const apartmentNumber = Number.parseInt(apartment, 10);

  return Boolean(fio)
    && fio.length <= CONFIG.MAX_FIO_LENGTH
    && /^\d{1,3}$/.test(apartment)
    && Number.isInteger(apartmentNumber)
    && apartmentNumber >= 1
    && apartmentNumber <= CONFIG.MAX_APARTMENT
    && Number.isInteger(numDevices)
    && numDevices >= 1
    && numDevices <= CONFIG.MAX_DEVICES;
}

function getRequiredSheet(spreadsheet, sheetName) {
  const sheet = spreadsheet.getSheetByName(sheetName);
  if (!sheet) {
    throw new Error(`Missing sheet: ${sheetName}`);
  }
  return sheet;
}

function reserveVouchers(passwordsSheet, requestsSheet, voucherCount) {
  const usedVouchers = getUsedVoucherSet(requestsSheet);
  const lastRow = passwordsSheet.getLastRow();

  if (lastRow < CONFIG.FIRST_DATA_ROW) {
    throwPublicError('No vouchers available');
  }

  const rowsToRead = lastRow - CONFIG.FIRST_DATA_ROW + 1;
  const values = passwordsSheet
    .getRange(CONFIG.FIRST_DATA_ROW, CONFIG.VOUCHER_COLUMN, rowsToRead, 1)
    .getValues()
    .map((row) => normalizeText(row[0]));

  const vouchers = [];
  let lastReservedRow = CONFIG.FIRST_DATA_ROW - 1;

  values.forEach((value, index) => {
    if (vouchers.length >= voucherCount || !value || usedVouchers.has(value)) {
      return;
    }
    vouchers.push(value);
    usedVouchers.add(value);
    lastReservedRow = CONFIG.FIRST_DATA_ROW + index;
  });

  if (vouchers.length < voucherCount) {
    throwPublicError(`Not enough vouchers. Needed ${voucherCount}, found ${vouchers.length}.`);
  }

  return { vouchers, lastReservedRow };
}

function getUsedVoucherSet(requestsSheet) {
  const used = new Set();
  const lastRow = requestsSheet.getLastRow();
  if (lastRow < 2) {
    return used;
  }

  const values = requestsSheet
    .getRange(2, CONFIG.ARCHIVE_VOUCHERS_COLUMN, lastRow - 1, 1)
    .getValues();

  values.forEach((row) => {
    String(row[0] || '')
      .split(/[;,\n]/)
      .map((value) => normalizeText(value))
      .filter(Boolean)
      .forEach((voucher) => used.add(voucher));
  });

  return used;
}

function appendArchiveRow(sheet, actor, details, vouchers) {
  const timestamp = Utilities.formatDate(
    new Date(),
    Session.getScriptTimeZone() || 'Europe/Moscow',
    'dd.MM.yyyy HH:mm:ss'
  );

  sheet.appendRow([
    timestamp,
    actor,
    details,
    vouchers.join(', ')
  ]);
}

function buildReservationDetails(data) {
  const parts = [];
  if (data.ru !== undefined) {
    parts.push(`RU: ${Number.parseInt(data.ru, 10) || 0}`);
  }
  if (data.en !== undefined) {
    parts.push(`EN: ${Number.parseInt(data.en, 10) || 0}`);
  }
  if (data.note) {
    parts.push(normalizeText(data.note));
  }
  return parts.join(' / ') || 'bulk reservation';
}

function rememberLastReservedRow(rowNumber) {
  if (Number.isInteger(rowNumber) && rowNumber >= CONFIG.FIRST_DATA_ROW) {
    PropertiesService
      .getScriptProperties()
      .setProperty(CONFIG.LAST_RESERVED_ROW_PROPERTY, String(rowNumber));
  }
}

function resetReservationDiagnostics() {
  PropertiesService.getScriptProperties().deleteProperty(CONFIG.LAST_RESERVED_ROW_PROPERTY);
  return 'Reservation diagnostics reset';
}

function getDebugState() {
  const spreadsheet = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  const passwordsSheet = getRequiredSheet(spreadsheet, CONFIG.PASSWORDS_SHEET);
  const requestsSheet = getRequiredSheet(spreadsheet, CONFIG.REQUESTS_SHEET);
  const usedVouchers = getUsedVoucherSet(requestsSheet);
  const props = PropertiesService.getScriptProperties();

  return {
    version: CONFIG.VERSION,
    passwordsLastRow: passwordsSheet.getLastRow(),
    requestsLastRow: requestsSheet.getLastRow(),
    usedVoucherCount: usedVouchers.size,
    lastReservedRow: props.getProperty(CONFIG.LAST_RESERVED_ROW_PROPERTY) || null
  };
}

function throwPublicError(message) {
  const error = new Error(message);
  error.publicMessage = message;
  throw error;
}

function jsonOut(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
