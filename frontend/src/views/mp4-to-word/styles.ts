export const QA_STYLE_FIX = `
.qa-section {
  margin-top: 14px;
  border-top: 1px solid rgba(15, 23, 42, 0.07);
  padding-top: 14px;
}
.qa-box {
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(255, 255, 255, 0.92);
  border-radius: 28px;
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.1);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
}
.qa-body {
  padding: 18px 18px 20px;
  background:
    radial-gradient(circle at 8% 0%, rgba(0, 113, 227, 0.05), transparent 28%),
    rgba(255, 255, 255, 0.2);
}
.qa-floating-anchor {
  height: 104px;
}
.qa-floating-wrap {
  position: fixed;
  left: 50%;
  bottom: 26px;
  transform: translateX(-50%);
  width: min(760px, calc(100vw - 32px));
  z-index: 45;
  pointer-events: none;
}
.qa-floating-shell {
  pointer-events: auto;
}
.qa-floating-inner {
  display: flex;
  align-items: center;
  gap: 12px;
}
.qa-search-box {
  position: relative;
  flex: 1;
}
.qa-search-input {
  width: 100%;
  padding: 14px 52px 14px 20px;
  border: 1.5px solid rgba(209, 213, 219, 0.95);
  border-radius: 18px;
  font-size: 14px;
  line-height: 1.4;
  color: #111827;
  background: rgba(255, 255, 255, 0.7);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
  transition: all 0.22s ease;
  outline: none;
}
.qa-search-input:focus {
  border-width: 2px;
  border-color: #0071e3;
  box-shadow: 0 16px 42px rgba(0, 113, 227, 0.16);
}
.qa-search-input::placeholder {
  color: #9ca3af;
}
.qa-search-icon {
  position: absolute;
  top: 50%;
  right: 16px;
  width: 22px;
  height: 22px;
  color: #6b7280;
  transform: translateY(-50%);
  pointer-events: none;
}
.qa-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.qa-empty {
  border-radius: 18px;
  padding: 16px;
  color: #86868b;
  font-size: 13px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px dashed rgba(15, 23, 42, 0.08);
}
.qa-item {
  background: rgba(255, 255, 255, 0.74) !important;
  border: 1px solid rgba(255, 255, 255, 0.96) !important;
  border-radius: 26px !important;
  overflow: hidden !important;
  margin-bottom: 0 !important;
  box-shadow: 0 18px 52px rgba(15, 23, 42, 0.08) !important;
  backdrop-filter: blur(18px) !important;
  -webkit-backdrop-filter: blur(18px) !important;
}
.qa-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px !important;
  cursor: pointer;
  gap: 12px;
  user-select: none;
  background: rgba(255, 255, 255, 0.68) !important;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06) !important;
}
.qa-item-header:hover {
  background: linear-gradient(180deg, rgba(247, 249, 252, 0.98) 0%, rgba(240, 243, 248, 0.95) 100%);
}
.qa-item-q-text {
  font-size: 13px !important;
  line-height: 1.45 !important;
  color: #1f2937 !important;
  font-weight: 680 !important;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 8px;
}
.qa-item-q-text.expanded { white-space: normal; }
.qa-item-q-text::before {
  content: 'Q' !important;
  width: 22px !important;
  height: 22px !important;
  border-radius: 10px !important;
  font-size: 10px !important;
  background: linear-gradient(135deg, #0a84ff, #0071e3) !important;
  color: #fff !important;
  box-shadow: 0 8px 16px rgba(0, 113, 227, 0.22) !important;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-weight: 700;
}
.qa-item-toggle {
  color: #86868b;
  transition: transform 0.25s ease;
  flex-shrink: 0;
}
.qa-item-toggle.open { transform: rotate(180deg); }
.qa-item-body {
  display: none;
  border-top: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(255, 255, 255, 0.5);
}
.qa-item-body.open { display: block; }
.qa-answer-body {
  max-height: 760px !important;
  padding: 10px 12px 12px !important;
  overflow-y: auto !important;
  background:
    radial-gradient(circle at 0% 0%, rgba(0, 113, 227, 0.04), transparent 28%),
    rgba(255, 255, 255, 0.24) !important;
}
.qa-answer-body::-webkit-scrollbar { width: 6px; }
.qa-answer-body::-webkit-scrollbar-track { background: transparent; }
.qa-answer-body::-webkit-scrollbar-thumb { background: rgba(110, 110, 115, 0.28); border-radius: 999px; }
.qa-answer {
  background: linear-gradient(135deg, rgba(0, 113, 227, 0.04), rgba(10, 132, 255, 0.06));
  border: 1px solid rgba(0, 113, 227, 0.12);
  border-radius: 16px;
  padding: 14px 16px;
  font-size: 13.5px;
  line-height: 1.85;
  color: #1d1d1f;
  white-space: pre-wrap;
  word-break: break-word;
}
.qa-item-body .qa-answer {
  margin: 0;
  border: none;
  background: none;
  padding: 0;
  font-size: 14px;
  line-height: 1.9;
  color: #1d1d1f;
  white-space: normal;
}
.qa-json-response {
  display: block;
  padding: 14px;
  background:
    radial-gradient(circle at 0% 0%, rgba(0, 113, 227, 0.08), transparent 35%),
    radial-gradient(circle at 100% 10%, rgba(52, 199, 89, 0.06), transparent 34%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.86), rgba(248, 250, 252, 0.84));
  border-radius: 18px;
  white-space: normal;
}
.qa-json-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.qa-json-eyebrow {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #0071e3;
}
.qa-json-title {
  margin-top: 4px;
  font-size: 20px;
  font-weight: 760;
  color: #111827;
  letter-spacing: -0.02em;
}
.qa-json-pills {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.qa-json-pill {
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.055);
  color: #6b7280;
  font-size: 11px;
  font-weight: 760;
}
.qa-json-pill.primary {
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
}
.qa-json-pill.accent {
  background: rgba(52, 199, 89, 0.12);
  color: #0f9f47;
}
.qa-json-pill.warn {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
}
.qa-json-core {
  position: relative;
  overflow: hidden;
  border-radius: 24px;
  padding: 18px;
  color: #fff;
  background:
    radial-gradient(circle at 96% 0%, rgba(255, 255, 255, 0.24), transparent 34%),
    linear-gradient(135deg, #0a84ff 0%, #0071e3 54%, #155bd5 100%);
  box-shadow: 0 18px 42px rgba(0, 113, 227, 0.22);
  margin-bottom: 14px;
}
.qa-json-core::after {
  content: "";
  position: absolute;
  right: -54px;
  bottom: -68px;
  width: 172px;
  height: 172px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
  pointer-events: none;
}
.qa-json-core-label {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.18);
  font-size: 12px;
  font-weight: 760;
  color: rgba(255, 255, 255, 0.96);
  margin-bottom: 12px;
}
.qa-json-core-mark {
  width: 20px;
  height: 20px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
  font-size: 11px;
}
.qa-json-core .qa-json-lines.compact {
  gap: 12px;
}
.qa-json-core .qa-json-line {
  color: rgba(255, 255, 255, 0.98);
  font-size: 15px;
  line-height: 1.88;
  font-weight: 680;
  letter-spacing: -0.01em;
}
.qa-json-core .qa-json-line-dot {
  width: 26px;
  height: 26px;
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
}
.qa-json-lines {
  display: grid;
  gap: 8px;
}
.qa-json-lines.compact { gap: 10px; }
.qa-json-line {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 10px;
  align-items: flex-start;
  color: #374151;
  font-size: 13px;
  line-height: 1.72;
}
.qa-json-line-dot {
  width: 24px;
  height: 24px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
  font-size: 11px;
  font-weight: 800;
}
.qa-json-line.risk .qa-json-line-dot {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
}
.qa-json-logic {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 12px;
  align-items: stretch;
  margin-bottom: 14px;
}
.qa-json-logic-pane {
  border-radius: 20px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(15, 23, 42, 0.06);
}
.qa-json-pane-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 12px;
}
.qa-json-pane-icon {
  width: 26px;
  height: 26px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
  font-weight: 800;
  flex-shrink: 0;
}
.qa-json-pane-title {
  font-size: 12px;
  font-weight: 780;
  color: #111827;
}
.qa-json-pane-subtitle {
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.5;
  color: #6e6e73;
}
.qa-json-flow-arrow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #0071e3;
  font-size: 18px;
  font-weight: 800;
}
.qa-json-support {
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
}
.qa-json-support.two { grid-template-columns: 1fr 1fr; }
.qa-json-support.one { grid-template-columns: 1fr; }
.qa-json-support-block {
  border-radius: 20px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(15, 23, 42, 0.06);
}
.qa-json-support-block.risk {
  background: linear-gradient(180deg, rgba(255, 247, 237, 0.98), rgba(255, 255, 255, 0.86));
  border-color: rgba(245, 158, 11, 0.18);
}
.qa-json-support-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 780;
  color: #111827;
  margin-bottom: 10px;
}
.qa-json-footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.qa-json-actions,
.qa-json-followups {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.qa-json-followups { margin-top: 14px; }
.qa-json-followup-label {
  font-size: 12px;
  font-weight: 760;
  color: #6e6e73;
}
.qa-action-btn,
.qa-followup-chip {
  border: 1px solid rgba(0, 113, 227, 0.12) !important;
  background: rgba(0, 113, 227, 0.075) !important;
  color: #0071e3 !important;
  border-radius: 999px !important;
  padding: 7px 11px !important;
  font-size: 12px !important;
  font-weight: 740 !important;
  cursor: pointer !important;
  display: inline-flex !important;
  align-items: center !important;
  gap: 6px !important;
  transition: all 0.18s ease !important;
  width: auto !important;
  height: auto !important;
}
.qa-action-btn:hover,
.qa-followup-chip:hover {
  transform: translateY(-1px);
  background: rgba(0, 113, 227, 0.12) !important;
}
.qa-json-disclaimer {
  font-size: 11px;
  line-height: 1.6;
  color: #6e6e73;
}
.qa-fallback-card {
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(15, 23, 42, 0.06);
  padding: 16px;
  font-size: 14px;
  line-height: 1.86;
  color: #1f2937;
}
.columns,
.result-box,
.summary-box,
.summary-stage,
.summary-workspace,
.qa-box,
.qa-json-response {
  min-width: 0;
  max-width: 100%;
}
.summary-workspace,
.qa-json-response,
.qa-json-core,
.qa-json-logic-pane,
.qa-json-support-block,
.qa-fallback-card {
  overflow-wrap: anywhere;
}
@media (max-width: 900px) {
  .qa-json-top,
  .qa-json-footer {
    flex-direction: column;
  }
  .qa-json-logic,
  .qa-json-support.two {
    grid-template-columns: 1fr;
  }
  .qa-json-flow-arrow {
    display: none;
  }
}
@media (max-width: 640px) {
  .columns {
    gap: 14px;
    margin-bottom: 14px;
  }
  .result-box,
  .summary-box,
  .qa-box {
    border-radius: 22px;
  }
  .result-header,
  .qa-item-header {
    align-items: flex-start;
    padding: 14px;
  }
  .result-title {
    min-width: 0;
    line-height: 1.35;
  }
  .result-meta {
    flex: 0 0 auto;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: flex-end;
  }
  .result-body {
    min-height: 280px;
    max-height: 58vh;
    padding: 16px;
    font-size: 14px;
    line-height: 1.8;
    overflow-x: auto;
  }
  .summary-stage {
    padding: 14px;
  }
  .summary-workspace {
    gap: 12px;
  }
  .summary-panel,
  .qa-json-core,
  .qa-json-logic-pane,
  .qa-json-support-block {
    border-radius: 18px;
    padding: 14px;
  }
  .qa-body {
    padding: 14px;
  }
  .qa-floating-anchor {
    height: 92px;
  }
  .qa-floating-wrap {
    bottom: 14px;
    width: calc(100vw - 24px);
  }
  .qa-floating-inner {
    gap: 8px;
    align-items: stretch;
  }
  .qa-search-box {
    width: 100%;
  }
  .qa-search-input {
    padding: 12px 44px 12px 14px;
    border-radius: 16px;
    font-size: 16px;
  }
  .qa-json-title {
    font-size: 17px;
    line-height: 1.35;
  }
  .qa-json-pills,
  .qa-json-actions,
  .qa-json-followups {
    justify-content: flex-start;
  }
  .qa-action-btn,
  .qa-followup-chip {
    max-width: 100%;
    white-space: normal;
    text-align: left;
  }
}
`;
