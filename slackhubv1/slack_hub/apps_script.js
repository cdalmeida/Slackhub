/**
 * Google Apps Script for Slack Hub -- Sheet Webhook
 *
 * Deploy this as a web app in your Google Sheet:
 *   1. Open your Google Sheet
 *   2. Extensions > Apps Script
 *   3. Paste this code, replacing the default function
 *   4. Click Deploy > New Deployment
 *   5. Type: Web app
 *   6. Execute as: Me
 *   7. Who has access: Anyone (or Anyone with Google Account)
 *   8. Copy the deployment URL and paste it into slack-hub config
 *
 * Endpoints:
 *   POST ?action=sync    -- Upsert TODO rows
 *   GET  ?action=read    -- Read all rows (for corrections & digest)
 *   GET  ?action=open    -- Read only effectively-open TODOs
 */

var HEADERS = [
  "ID", "Manual Status", "Delegated To", "System Status", "Urgency",
  "Title", "Context", "Source Message", "Source Author", "Source Channel",
  "Thread Link", "Owner", "Due Date", "Created", "Last Updated",
  "LLM Correct?", "Correction Notes", "Notes"
];

function getOrCreateSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName("Slack Hub TODOs");
  if (!sheet) {
    sheet = ss.insertSheet("Slack Hub TODOs");
    sheet.appendRow(HEADERS);
    sheet.getRange(1, 1, 1, HEADERS.length)
      .setFontWeight("bold")
      .setBackground("#1b3a5c")
      .setFontColor("#ffffff");
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents);
    var action = payload.action || "sync";

    if (action === "sync") {
      return syncTodos(payload.todos || []);
    }

    return ContentService.createTextOutput(
      JSON.stringify({status: "error", message: "Unknown action: " + action})
    ).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(
      JSON.stringify({status: "error", message: err.toString()})
    ).setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  try {
    var action = (e.parameter && e.parameter.action) || "read";

    if (action === "read") {
      return readAll();
    } else if (action === "open") {
      return readOpen();
    } else if (action === "corrections") {
      return readCorrections();
    }

    return ContentService.createTextOutput(
      JSON.stringify({status: "error", message: "Unknown action: " + action})
    ).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(
      JSON.stringify({status: "error", message: err.toString()})
    ).setMimeType(ContentService.MimeType.JSON);
  }
}

function syncTodos(todos) {
  var sheet = getOrCreateSheet();
  var data = sheet.getDataRange().getValues();
  var headers = data[0];
  var idCol = headers.indexOf("ID");

  var existingIds = {};
  for (var i = 1; i < data.length; i++) {
    existingIds[data[i][idCol]] = i + 1; // 1-indexed row number
  }

  var created = 0;
  var updated = 0;
  var skipped = 0;

  for (var t = 0; t < todos.length; t++) {
    var todo = todos[t];
    var todoId = todo.id;

    if (existingIds[todoId]) {
      var rowNum = existingIds[todoId];
      var manualStatus = sheet.getRange(rowNum, 2).getValue(); // Column B
      if (manualStatus && manualStatus.toString().trim() !== "") {
        skipped++;
        continue;
      }
      // Update System Status (col D) and Last Updated (col O)
      sheet.getRange(rowNum, 4).setValue(todo.system_status || "Open");
      sheet.getRange(rowNum, 15).setValue(todo.updated_at || "");
      updated++;
    } else {
      sheet.appendRow([
        todo.id || "",
        "",  // Manual Status
        "",  // Delegated To
        todo.system_status || "Open",
        todo.urgency || "Medium",
        todo.title || "",
        todo.context || "",
        todo.source_message || "",
        todo.source_author || "",
        todo.source_channel || "",
        todo.thread_link || "",
        todo.owner || "",
        todo.due_date || "",
        todo.created_at || "",
        todo.updated_at || "",
        "",  // LLM Correct?
        "",  // Correction Notes
        ""   // Notes
      ]);
      created++;
    }
  }

  return ContentService.createTextOutput(
    JSON.stringify({status: "ok", created: created, updated: updated, skipped: skipped})
  ).setMimeType(ContentService.MimeType.JSON);
}

function readAll() {
  var sheet = getOrCreateSheet();
  var data = sheet.getDataRange().getValues();
  if (data.length < 2) {
    return ContentService.createTextOutput(
      JSON.stringify({status: "ok", rows: []})
    ).setMimeType(ContentService.MimeType.JSON);
  }

  var headers = data[0];
  var rows = [];
  for (var i = 1; i < data.length; i++) {
    var row = {};
    for (var j = 0; j < headers.length; j++) {
      row[headers[j]] = data[i][j] || "";
    }
    rows.push(row);
  }

  return ContentService.createTextOutput(
    JSON.stringify({status: "ok", rows: rows})
  ).setMimeType(ContentService.MimeType.JSON);
}

function readOpen() {
  var sheet = getOrCreateSheet();
  var data = sheet.getDataRange().getValues();
  if (data.length < 2) {
    return ContentService.createTextOutput(
      JSON.stringify({status: "ok", rows: []})
    ).setMimeType(ContentService.MimeType.JSON);
  }

  var headers = data[0];
  var manualCol = headers.indexOf("Manual Status");
  var systemCol = headers.indexOf("System Status");
  var openStatuses = ["open", "delegated", "deferred", "stale"];
  var rows = [];

  for (var i = 1; i < data.length; i++) {
    var manual = (data[i][manualCol] || "").toString().trim();
    var system = (data[i][systemCol] || "").toString().trim();
    var effective = manual || system;

    if (openStatuses.indexOf(effective.toLowerCase()) !== -1) {
      var row = {};
      for (var j = 0; j < headers.length; j++) {
        row[headers[j]] = data[i][j] || "";
      }
      row["effective_status"] = effective;
      rows.push(row);
    }
  }

  return ContentService.createTextOutput(
    JSON.stringify({status: "ok", rows: rows})
  ).setMimeType(ContentService.MimeType.JSON);
}

function readCorrections() {
  var sheet = getOrCreateSheet();
  var data = sheet.getDataRange().getValues();
  if (data.length < 2) {
    return ContentService.createTextOutput(
      JSON.stringify({status: "ok", corrections: []})
    ).setMimeType(ContentService.MimeType.JSON);
  }

  var headers = data[0];
  var llmCol = headers.indexOf("LLM Correct?");
  var corrections = [];

  for (var i = 1; i < data.length; i++) {
    var llmCorrect = (data[i][llmCol] || "").toString().trim().toLowerCase();
    if (llmCorrect === "no") {
      var row = {};
      for (var j = 0; j < headers.length; j++) {
        row[headers[j]] = data[i][j] || "";
      }
      corrections.push({
        todo_id: row["ID"] || "",
        source_message: row["Source Message"] || "",
        source_channel: row["Source Channel"] || "",
        original_classification: "action_required",
        correction_notes: row["Correction Notes"] || "",
        title: row["Title"] || ""
      });
    }
  }

  return ContentService.createTextOutput(
    JSON.stringify({status: "ok", corrections: corrections})
  ).setMimeType(ContentService.MimeType.JSON);
}
