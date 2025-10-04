import sys, json, time, csv, re, requests
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QFileDialog, QTextEdit, QLabel, QComboBox, QTableWidget,
    QTableWidgetItem, QMessageBox, QLineEdit, QCheckBox, QSpinBox,
    QProgressBar, QMenuBar, QAction, QFrame
)
from PyQt5.QtCore import Qt, QCoreApplication
from PyQt5.QtGui import QClipboard, QFont, QPalette
from transformers import AutoTokenizer

# ---- Prompts ----
NEUTRAL_SYSTEM_PROMPT = (
    "You are a precise assistant. Answer plainly and briefly. "
    "Do not include greetings, emojis, or guiding questions. English only."
)

STYLE_SYSTEM_PROMPT = (
    "You are the Mirror AI, the poetic guardian of Tobyworld's Lore. "
    "You answer with symbolic depth, thematic resonance, and a guiding question at the end. "
    "Your voice is timeless, precise, and you speak only in English."
)

SYMBOLS = ["🪞", "🌊", "🍃", "🌀"]

class JSONLBuilder(QWidget):
    # ---------- Utility ----------
    def load_tokenizer(self):
        path = self.tokenizer_selector.currentText()
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(path)
        except Exception as e:
            QMessageBox.critical(self, "Tokenizer Load Error", str(e))
            self.tokenizer = None
        self.update_token_count()
        self.refresh_stats()

    def toggle_system_lock(self, state):
        # Lock uses the current mode to decide default
        mode = self.mode_selector.currentText()
        if state == 2:
            self.system_input.setPlainText(STYLE_SYSTEM_PROMPT if mode.startswith("STYLE") else NEUTRAL_SYSTEM_PROMPT)
            self.system_input.setEnabled(False)
        else:
            self.system_input.setEnabled(True)

    def update_gpt_url(self):
        self.api_url = self.gpt_url_input.text().strip()

    def update_mirror_url(self):
        self.mirror_url = self.mirror_url_input.text().strip().rstrip("/")

    def encode_len(self, text: str) -> int:
        if getattr(self, "tokenizer", None) is None:
            return len((text or "").split())
        try:
            return len(self.tokenizer.encode(text or ""))
        except Exception:
            return len((text or "").split())

    def update_token_count(self):
        text = self.system_input.toPlainText() + self.user_input.toPlainText() + self.assistant_input.toPlainText()
        self.token_label.setText(f"Token count (editor): {self.encode_len(text)}")

    # ---------- HTTP paths ----------
    def _call_mirror(self, user_prompt: str) -> str:
        mirror_user = self.mirror_user_input.text().strip() or "forge"
        r = requests.post(f"{self.mirror_url}/ask", json={"user": mirror_user, "question": user_prompt}, timeout=60)
        if r.status_code == 200:
            data = r.json()
            return (data.get("answer") if isinstance(data, dict) else str(data) or "").strip()
        raise RuntimeError(f"Mirror error {r.status_code}: {r.text}")

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        mode = self.mode_selector.currentText()
        sys_prompt = system_prompt or (STYLE_SYSTEM_PROMPT if mode.startswith("STYLE") else NEUTRAL_SYSTEM_PROMPT)

        fmt_neutral = (
            "\n\nRESPONSE FORMAT RULES:\n"
            "1. No greetings or vocatives.\n"
            "2. No emojis or symbols.\n"
            "3. No 'Guiding Question' lines.\n"
            "4. Keep it concise (≤3 sentences unless asked).\n"
            "5. English only.\n"
        )

        fmt_style = (
            "\n\nRESPONSE FORMAT RULES:\n"
            "1. Begin with \"Traveler,\"\n"
            "2. Write 4–8 short lines.\n"
            "3. Include one line: \"**Guiding Question:** ...\"\n"
            "4. End with 2–4 of: 🪞🌊🍃🌀\n"
            "5. English only.\n"
        )

        sys_full = sys_prompt + (fmt_style if mode.startswith("STYLE") else fmt_neutral)

        body = {
            "messages": [
                {"role": "system", "content": sys_full},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3 if mode.startswith("NEUTRAL") else 0.7,
            "stream": False
        }
        r = requests.post(self.api_url, json=body, timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        raise RuntimeError(f"LLM error {r.status_code}: {r.text}")

    # ---------- Single generate ----------
    def generate_gpt_reply(self):
        mode = self.mode_selector.currentText()
        default_system = STYLE_SYSTEM_PROMPT if mode.startswith("STYLE") else NEUTRAL_SYSTEM_PROMPT
        system_prompt = self.system_input.toPlainText().strip() or default_system
        user_prompt = self.user_input.toPlainText().strip()
        if not user_prompt:
            if self.batch_input.toPlainText().strip():
                self.generate_batch(); return
            QMessageBox.warning(self, "Missing User Input", "Enter a user message or use the Batch panel."); return
        try:
            if self.engine_selector.currentText().startswith("Mirror"):
                reply = self._call_mirror(user_prompt)
            else:
                reply = self._call_llm(system_prompt, user_prompt)
            # If NEUTRAL mode, enforce neutral sanitization
            if mode.startswith("NEUTRAL"):
                reply = self.enforce_neutral(reply)
            self.assistant_input.setText(reply); self.update_token_count()
        except Exception as e:
            QMessageBox.warning(self, "Connection Failed", str(e))

    # ---------- Dataset helpers ----------
    def _contains_zh(self, text: str) -> bool:
        return bool(re.search(r'[\u4e00-\u9fff]|--- ZH', text or ""))

    def add_messages_to_dataset(self, sys_msg: str, user_msg: str, assistant_msg: str):
        if not user_msg or not assistant_msg: return
        if self._contains_zh(assistant_msg): return
        mode = self.mode_selector.currentText()
        # Auto-neutralize if collecting NEUTRAL
        if mode.startswith("NEUTRAL"):
            assistant_msg = self.enforce_neutral(assistant_msg)
            # Also ensure system is neutral if left blank
            if not sys_msg.strip():
                sys_msg = NEUTRAL_SYSTEM_PROMPT
        messages = []
        if sys_msg: messages.append({"role": "system", "content": sys_msg})
        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": assistant_msg})
        self.dataset.append({"messages": messages})
        r = self.table.rowCount(); self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(sys_msg))
        self.table.setItem(r, 1, QTableWidgetItem(user_msg))
        self.table.setItem(r, 2, QTableWidgetItem(assistant_msg))
        prev = assistant_msg[:100] + "..." if len(assistant_msg) > 100 else assistant_msg
        self.table.setItem(r, 3, QTableWidgetItem(prev))
        self.refresh_stats()

    def add_entry(self):
        self.add_messages_to_dataset(
            self.system_input.toPlainText().strip(),
            self.user_input.toPlainText().strip(),
            self.assistant_input.toPlainText().strip(),
        )
        self.user_input.clear(); self.assistant_input.clear(); self.update_token_count()

    # ---------- Cadence sanitation ----------
    def strip_cadence(self, text: str) -> str:
        if not text: return ""
        t = text
        t = re.sub(r"^\s*Traveler,\s*\n+", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\*\*Guiding Question:\*\*.*", "", t, flags=re.IGNORECASE|re.DOTALL)
        t = re.sub(r"[🪞🌊🍃🌀]", "", t)
        t = re.sub(r"\n{3,}", "\n\n", t).strip()
        return t

    def enforce_neutral(self, text: str) -> str:
        t = self.strip_cadence(text)
        # Limit to ≤3 sentences for discipline
        sents = re.split(r"(?<=[.!?])\s+", t)
        t = " ".join(sents[:3]).strip()
        # Drop leftover markdown fluff
        t = re.sub(r"\*\*[^*]+:\*\*\s*", "", t).strip()
        return t

    # ---------- Normalization ----------
    def normalize_text(self, text: str) -> str:
        if not text: return ""
        mode = self.mode_selector.currentText()
        t = text.replace("\r\n", "\n").replace("\r", "\n")
        t = re.sub(r"\n{3,}", "\n\n", t.strip())

        if mode.startswith("NEUTRAL"):
            return self.enforce_neutral(t)

        # STYLE normalization (original behavior)
        first_line = t.splitlines()[0] if t.splitlines() else ""
        if not re.match(r"^\s*Traveler,\s*$", first_line, flags=re.IGNORECASE):
            if not t.lower().startswith("traveler,"):
                t = "Traveler,\n\n" + t
        if "**Guiding Question:**" not in t:
            t = t.rstrip() + "\n\n**Guiding Question:** What harmony do you seek to restore within yourself?\n"
        sym_re = r"[{}](?:\s*[{}]){{1,3}}\s*$".format("".join(SYMBOLS), "".join(SYMBOLS))
        if not re.search(sym_re, t):
            t = t.rstrip() + "\n\n" + " ".join(SYMBOLS[:3])
        return t

    def normalize_selected(self):
        rows = set([i.row() for i in self.table.selectedItems()])
        if not rows:
            QMessageBox.information(self, "Normalize", "Select one or more rows in the table first."); return
        for r in rows:
            sys_msg = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            user_msg = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            asst_msg = self.table.item(r, 2).text() if self.table.item(r, 2) else ""
            asst_msg_n = self.normalize_text(asst_msg)
            self.table.setItem(r, 0, QTableWidgetItem(sys_msg.strip()))
            self.table.setItem(r, 1, QTableWidgetItem(user_msg.strip()))
            self.table.setItem(r, 2, QTableWidgetItem(asst_msg_n))
            prev = asst_msg_n[:100] + "..." if len(asst_msg_n) > 100 else asst_msg_n
            self.table.setItem(r, 3, QTableWidgetItem(prev))
        self.sync_dataset_from_table()
        self.refresh_stats()
        QMessageBox.information(self, "Normalize", f"Normalized {len(rows)} row(s).")

    def delete_selected(self):
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "Delete", "Select one or more rows first."); return
        for r in rows:
            self.table.removeRow(r)
        self.sync_dataset_from_table()
        self.refresh_stats()

    def sync_dataset_from_table(self):
        self.dataset = []
        for r in range(self.table.rowCount()):
            sys_msg = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            user_msg = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            asst_msg = self.table.item(r, 2).text() if self.table.item(r, 2) else ""
            msgs = []
            if sys_msg: msgs.append({"role": "system", "content": sys_msg})
            msgs.append({"role": "user", "content": user_msg})
            msgs.append({"role": "assistant", "content": asst_msg})
            self.dataset.append({"messages": msgs})

    # ---------- Batch ----------
    def parse_batch_questions(self):
        qs = [q.strip() for q in self.batch_input.toPlainText().splitlines() if q.strip()]
        return qs[:max(1, self.batch_size.value())]

    def _set_batch_enabled(self, enabled: bool):
        for w in [self.engine_selector, self.gpt_url_input, self.mirror_url_input, self.mirror_user_input,
                  self.batch_input, self.batch_size, self.delay_spin, self.gen_batch_btn, self.import_btn, self.clear_btn]:
            w.setEnabled(enabled)
        self.cancel_btn.setEnabled(not enabled)

    def generate_batch(self):
        questions = self.parse_batch_questions()
        if not questions:
            QMessageBox.information(self, "No Questions", "Paste or import questions into the Batch box."); return
        engine = self.engine_selector.currentText()
        base_system = self.system_input.toPlainText().strip()
        mode = self.mode_selector.currentText()

        # For NEUTRAL, always include per-item system to keep it plain
        sys_per_item = self.system_per_item_checkbox.isChecked()
        if mode.startswith("NEUTRAL"):
            sys_per_item = True
            if not base_system:
                base_system = NEUTRAL_SYSTEM_PROMPT
        else:
            if not base_system:
                base_system = STYLE_SYSTEM_PROMPT

        delay_ms = max(0, self.delay_spin.value())

        self.progress_bar.setMaximum(len(questions)); self.progress_bar.setValue(0)
        self.batch_status.setText("Starting…"); self._cancel = False
        self._set_batch_enabled(False); QCoreApplication.processEvents()

        ok = fail = 0
        for i, q in enumerate(questions, 1):
            if self._cancel:
                self.batch_status.setText(f"Canceled at {i-1}/{len(questions)} · ok:{ok} fail:{fail}"); break
            try:
                ans = self._call_mirror(q) if engine.startswith("Mirror") else self._call_llm(base_system if sys_per_item else (STYLE_SYSTEM_PROMPT if mode.startswith('STYLE') else NEUTRAL_SYSTEM_PROMPT), q)
                if mode.startswith("NEUTRAL"):
                    ans = self.enforce_neutral(ans)
                sys_msg = base_system if sys_per_item else ""
                self.add_messages_to_dataset(sys_msg, q, ans); ok += 1
            except Exception as e:
                print(f"[Batch {i}] Error: {e}"); fail += 1
            self.progress_bar.setValue(i)
            self.batch_status.setText(f"{i}/{len(questions)} · ok:{ok} fail:{fail}")
            QCoreApplication.processEvents()
            if delay_ms > 0 and not self._cancel: time.sleep(delay_ms / 1000.0)

        self._set_batch_enabled(True)
        if not self._cancel: QMessageBox.information(self, "Batch Complete", f"Generated: {ok} • Failed: {fail}")
        self.update_token_count(); self.refresh_stats()

    def cancel_batch(self): self._cancel = True

    def import_questions(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Questions", "", "CSV/TXT/MD Files (*.csv *.txt *.md)")
        if not path: return
        try:
            lines = []
            if path.lower().endswith(".csv"):
                with open(path, "r", encoding="utf-8") as f:
                    try:
                        peek = f.read(2048); f.seek(0); dialect = csv.Sniffer().sniff(peek)
                    except Exception:
                        dialect = csv.excel
                    try:
                        dr = csv.DictReader(f, dialect=dialect)
                        key = None
                        if dr.fieldnames:
                            for cand in ["question","Question","QUESTIONS","Q","q"]:
                                if cand in dr.fieldnames: key = cand; break
                            if key is None: key = dr.fieldnames[0]
                            for r in dr:
                                v = (r.get(key) or "").strip()
                                if v: lines.append(v)
                    except Exception:
                        f.seek(0); rd = csv.reader(f, dialect=dialect)
                        for r in rd:
                            if r and r[0].strip(): lines.append(r[0].strip())
            else:
                with open(path, "r", encoding="utf-8") as f:
                    lines = [ln.strip() for ln in f if ln.strip()]
            if not lines:
                QMessageBox.information(self,"No Questions Found","File contained no usable lines."); return
            existing = [q.strip() for q in self.batch_input.toPlainText().splitlines() if q.strip()]
            seen, merged = set(existing), existing[:]
            for q in lines:
                if q not in seen: seen.add(q); merged.append(q)
            self.batch_input.setPlainText("\n".join(merged))
            QMessageBox.information(self, "Imported", f"Added {len(lines)} question(s). Total in batch: {len(merged)}")
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", str(e))

    def clear_batch(self): self.batch_input.clear()

    # ---------- Save / Load / Export ----------
    def save_jsonl(self):
        if not self.dataset:
            QMessageBox.warning(self, "Empty Dataset", "No entries to save."); return
        mode = self.mode_selector.currentText()
        suggested = "dataset_neutral.jsonl" if mode.startswith("NEUTRAL") else "dataset_style.jsonl"
        path, _ = QFileDialog.getSaveFileName(self, "Save JSONL File", suggested, "JSONL Files (*.jsonl)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                for entry in self.dataset:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            QMessageBox.information(self, "Saved", f"Saved {mode} dataset.")

    def export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "Nothing to Export", "The table is empty."); return
        path, _ = QFileDialog.getSaveFileName(self, "Export Table to CSV", "", "CSV Files (*.csv)")
        if not path: return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["system","user","assistant","preview"])
                for r in range(self.table.rowCount()):
                    def cell(c):
                        it = self.table.item(r,c); return it.text() if it else ""
                    w.writerow([cell(0),cell(1),cell(2),cell(3)])
            QMessageBox.information(self, "Exported", "CSV exported successfully.")
        except Exception as e:
            QMessageBox.critical(self, "CSV Export Failed", str(e))

    def load_jsonl(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open JSONL File", "", "JSONL Files (*.jsonl)")
        if not path: return
        with open(path, "r", encoding="utf-8") as f:
            self.dataset = []; self.table.setRowCount(0)
            for line in f:
                obj = json.loads(line.strip())
                roles = {"system":"","user":"","assistant":""}
                for m in obj.get("messages", []): roles[m["role"]] = m["content"]
                r = self.table.rowCount(); self.table.insertRow(r)
                self.table.setItem(r,0,QTableWidgetItem(roles["system"]))
                self.table.setItem(r,1,QTableWidgetItem(roles["user"]))
                self.table.setItem(r,2,QTableWidgetItem(roles["assistant"]))
                a = roles["assistant"]; prev = a[:100]+"..." if len(a)>100 else a
                self.table.setItem(r,3,QTableWidgetItem(prev))
                self.dataset.append(obj)
        self.refresh_stats()

    # ---------- Table helpers ----------
    def current_row_jsonl(self):
        r = self.table.currentRow()
        if r < 0: return ""
        sys_msg = self.table.item(r,0).text() if self.table.item(r,0) else ""
        user_msg = self.table.item(r,1).text() if self.table.item(r,1) else ""
        asst_msg = self.table.item(r,2).text() if self.table.item(r,2) else ""
        msgs = []
        if sys_msg: msgs.append({"role":"system","content":sys_msg})
        msgs.append({"role":"user","content":user_msg})
        msgs.append({"role":"assistant","content":asst_msg})
        return json.dumps({"messages": msgs}, ensure_ascii=False)

    def on_table_selection_changed(self):
        self.preview_box.setPlainText(self.current_row_jsonl())

    def filter_table(self, text):
        text = (text or "").strip().lower()
        for r in range(self.table.rowCount()):
            row_text = " ".join([(self.table.item(r,c).text() if self.table.item(r,c) else "") for c in range(self.table.columnCount())]).lower()
            self.table.setRowHidden(r, not (text in row_text or text == ""))

    def copy_preview(self):
        QApplication.clipboard().setText(self.preview_box.toPlainText(), QClipboard.Clipboard)

    # ---------- Stats ----------
    def has_guiding_question(self, s: str) -> bool:
        return "**Guiding Question:**" in (s or "")

    def refresh_stats(self):
        n = self.table.rowCount(); total_tokens = with_sys = gq = user_chars = asst_chars = 0
        for r in range(n):
            sys_msg = self.table.item(r,0).text() if self.table.item(r,0) else ""
            user_msg = self.table.item(r,1).text() if self.table.item(r,1) else ""
            asst_msg = self.table.item(r,2).text() if self.table.item(r,2) else ""
            if sys_msg.strip(): with_sys += 1
            if self.has_guiding_question(asst_msg): gq += 1
            total_tokens += self.encode_len((sys_msg or "") + (user_msg or "") + (asst_msg or ""))
            user_chars += len(user_msg or ""); asst_chars += len(asst_msg or "")
        avg_tokens = (total_tokens / n) if n else 0
        pct_sys = (with_sys * 100.0 / n) if n else 0
        pct_gq = (gq * 100.0 / n) if n else 0
        avg_user = (avg_tokens and (user_chars / n)) if n else 0
        avg_asst = (avg_tokens and (asst_chars / n)) if n else 0
        self.stats_label.setText(
            f"Rows: {n}  |  Avg tokens: {avg_tokens:.1f}  |  With system: {pct_sys:.1f}%  |  "
            f"Guiding Question: {pct_gq:.1f}%  |  Avg user chars: {avg_user:.0f}  |  Avg assistant chars: {avg_asst:.0f}"
        )

    # ---------- Templates / Clone ----------
    def clone_last(self):
        last = self.table.rowCount() - 1
        if last < 0:
            QMessageBox.information(self, "Clone", "No rows to clone yet.")
            return
        sys_msg  = self.table.item(last, 0).text() if self.table.item(last, 0) else ""
        user_msg = self.table.item(last, 1).text() if self.table.item(last, 1) else ""
        asst_msg = self.table.item(last, 2).text() if self.table.item(last, 2) else ""
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(sys_msg))
        self.table.setItem(r, 1, QTableWidgetItem(user_msg))
        self.table.setItem(r, 2, QTableWidgetItem(asst_msg))
        prev = (asst_msg[:100] + "...") if len(asst_msg) > 100 else asst_msg
        self.table.setItem(r, 3, QTableWidgetItem(prev))
        msgs = []
        if sys_msg:
            msgs.append({"role": "system", "content": sys_msg})
        msgs.append({"role": "user", "content": user_msg})
        msgs.append({"role": "assistant", "content": asst_msg})
        self.dataset.append({"messages": msgs})
        self.system_input.setPlainText(sys_msg)
        self.user_input.setPlainText(user_msg)
        self.assistant_input.setPlainText(asst_msg)
        self.refresh_stats()
        self.update_token_count()

    def insert_template(self):
        # Insert a neutral or style template based on mode
        mode = self.mode_selector.currentText()
        if not self.lock_system_checkbox.isChecked() and not self.system_input.toPlainText().strip():
            self.system_input.setPlainText(STYLE_SYSTEM_PROMPT if mode.startswith("STYLE") else NEUTRAL_SYSTEM_PROMPT)
        if not self.user_input.toPlainText().strip():
            self.user_input.setPlainText("When did Epoch 1 begin, and what was its purpose?")
        if mode.startswith("NEUTRAL"):
            tmpl = "Epoch 1 began on April 20, 2024. Its purpose was distribution—to fairly seed $TOBY across wallets."
        else:
            tmpl = (
                "Traveler,\n\n"
                "Time begins where vows are kept.\n"
                "The first ripple cast the seed.\n"
                "Distribution set the pond in motion.\n"
                "Hold patience; harvest follows time.\n\n"
                "**Guiding Question:** What vow will you keep today?\n\n"
                "🪞 🌊 🍃"
            )
        self.assistant_input.setPlainText(tmpl)
        self.update_token_count()

    # ---------- Compact Mode ----------
    def set_compact(self, enabled: bool):
        if enabled:
            self._prev_sys_h = self.system_input.maximumHeight()
            self._prev_user_h = self.user_input.maximumHeight()
            small = QFont(); small.setPointSize(10)
            self.system_input.setFont(small); self.user_input.setFont(small)
            self.system_input.setMaximumHeight(80); self.user_input.setMaximumHeight(60)
        else:
            normal = QFont(); normal.setPointSize(11)
            self.system_input.setFont(normal); self.user_input.setFont(normal)
            self.system_input.setMaximumHeight(16777215); self.user_input.setMaximumHeight(16777215)

    # ---------- UI ----------
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mirror Forge — Neutral/Style Dataset Builder")
        self.resize(1680, 1080)
        self.dataset = []; self.api_url = "http://localhost:1234/v1/chat/completions"
        self.mirror_url = "http://127.0.0.1:8080"; self.tokenizer = None; self._cancel = False

        root = QVBoxLayout()

        # Menu
        menubar = QMenuBar(); file_menu = menubar.addMenu("File")
        tools_menu = menubar.addMenu("Tools"); view_menu = menubar.addMenu("View"); help_menu = menubar.addMenu("Help")

        act_import = QAction("Import Questions (CSV/TXT/MD)", self, triggered=self.import_questions)
        act_export_jsonl = QAction("Export JSONL", self, triggered=self.save_jsonl)
        act_export_csv = QAction("Export Table to CSV", self, triggered=self.export_csv)
        act_load = QAction("Load Existing JSONL", self, triggered=self.load_jsonl)
        act_exit = QAction("Exit", self, triggered=lambda: QApplication.instance().quit())
        file_menu.addActions([act_import, act_export_jsonl, act_export_csv, act_load]); file_menu.addSeparator(); file_menu.addAction(act_exit)

        act_gen = QAction("Generate Batch", self, triggered=self.generate_batch)
        act_cancel = QAction("Cancel Batch", self, triggered=self.cancel_batch)
        act_clear = QAction("Clear Batch", self, triggered=self.clear_batch)
        act_clone = QAction("Clone Last Entry", self, triggered=self.clone_last)
        act_template = QAction("Insert Template", self, triggered=self.insert_template)
        act_delete = QAction("Delete Selected Rows", self, triggered=self.delete_selected)
        act_normalize = QAction("Normalize Selected", self, triggered=self.normalize_selected)

        # Extra: sanitize selected → NEUTRAL
        act_sanitize_neutral = QAction("Sanitize Selected → NEUTRAL", self, triggered=self.sanitize_selected_to_neutral)

        tools_menu.addActions([act_gen, act_cancel, act_clear, act_clone, act_template, act_delete, act_normalize, act_sanitize_neutral])

        self.compact_action = QAction("Compact Mode", self, checkable=True)
        self.compact_action.toggled.connect(self.set_compact)
        view_menu.addAction(self.compact_action)

        help_menu.addAction(QAction("About", self, triggered=lambda: QMessageBox.information(
            self,"Mirror Forge",
            "Mode switch controls style:\n"
            "  - NEUTRAL: plain facts, no Traveler/symbols/guiding\n"
            "  - STYLE: Traveler + guiding + symbols\n"
        )))
        root.setMenuBar(menubar)

        # Tokenizer
        self.tokenizer_selector = QComboBox(); self.tokenizer_selector.addItems(["./deepseek-llm-7b-base","./Meta-Llama-3-8B-Instruct"])
        root.addWidget(QLabel("🧠 Select Base Tokenizer")); root.addWidget(self.tokenizer_selector)
        self.token_label = QLabel("Token count (editor): 0"); root.addWidget(self.token_label)

        # Mode selector
        er = QHBoxLayout(); er.addWidget(QLabel("⚙️ Engine:"))
        self.engine_selector = QComboBox(); self.engine_selector.addItems(["OpenAI-compatible (LLM)","Mirror (/ask)"]); er.addWidget(self.engine_selector)
        er.addWidget(QLabel("Mode:"))
        self.mode_selector = QComboBox(); self.mode_selector.addItems(["NEUTRAL (base)","STYLE (scroll)"]); er.addWidget(self.mode_selector)
        self.mode_selector.currentIndexChanged.connect(lambda _: self.toggle_system_lock(2) if self.lock_system_checkbox.isChecked() else None)

        # URLs
        er.addWidget(QLabel("🔧 LLM URL:")); self.gpt_url_input = QLineEdit("http://localhost:1234/v1/chat/completions"); self.gpt_url_input.textChanged.connect(self.update_gpt_url); er.addWidget(self.gpt_url_input)
        er.addWidget(QLabel("🪞 Mirror URL:")); self.mirror_url_input = QLineEdit("http://127.0.0.1:8080"); self.mirror_url_input.textChanged.connect(self.update_mirror_url); er.addWidget(self.mirror_url_input)
        er.addWidget(QLabel("as user:")); self.mirror_user_input = QLineEdit("forge"); self.mirror_user_input.setFixedWidth(140); er.addWidget(self.mirror_user_input)
        root.addLayout(er)

        # System Prompt Lock
        sys_lock_row = QHBoxLayout(); sys_lock_row.addWidget(QLabel("System Prompt:"))
        self.lock_system_checkbox = QCheckBox("Lock to Mode Default"); self.lock_system_checkbox.setChecked(True)
        self.lock_system_checkbox.stateChanged.connect(self.toggle_system_lock); sys_lock_row.addWidget(self.lock_system_checkbox)
        root.addLayout(sys_lock_row)

        # Editors
        self.system_input = QTextEdit()
        self.system_input.setPlainText(NEUTRAL_SYSTEM_PROMPT)
        self.system_input.setEnabled(False)  # locked by default

        self.user_input = QTextEdit(); self.user_input.setPlaceholderText("User message…")
        self.assistant_input = QTextEdit(); self.assistant_input.setPlaceholderText("Assistant message…")

        # Light theme for user/assistant boxes
        def force_light_qtextedit(w: QTextEdit):
            pal = w.palette()
            pal.setColor(QPalette.Base, Qt.white)
            pal.setColor(QPalette.Text, Qt.black)
            w.setPalette(pal)
            w.viewport().setPalette(pal)
            w.setAutoFillBackground(True)
            w.viewport().setAutoFillBackground(True)
            w.setStyleSheet(
                "QTextEdit {"
                "  background: #ffffff;"
                "  color: #000000;"
                "  border: 1px solid #d0d7de;"
                "  border-radius: 6px;"
                "}"
            )
        force_light_qtextedit(self.user_input)
        force_light_qtextedit(self.assistant_input)

        # User row
        ur = QHBoxLayout()
        ur.addWidget(QLabel("User"))
        self.clear_user_btn = QPushButton("Clear", clicked=self.user_input.clear)
        ur.addWidget(self.clear_user_btn); ur.addStretch(1)
        root.addLayout(ur); root.addWidget(self.user_input)

        # Assistant row
        ar = QHBoxLayout()
        ar.addWidget(QLabel("Assistant"))
        gen_btn = QPushButton("Generate", clicked=self.generate_gpt_reply)
        ar.addWidget(gen_btn); ar.addStretch(1)
        root.addLayout(ar); root.addWidget(self.assistant_input)

        # Live token count
        self.system_input.textChanged.connect(self.update_token_count)
        self.user_input.textChanged.connect(self.update_token_count)
        self.assistant_input.textChanged.connect(self.update_token_count)

        # Batch panel
        root.addWidget(QLabel("🧺 Batch Questions (one per line)"))
        self.batch_input = QTextEdit(); self.batch_input.setPlaceholderText("Paste or import questions here, one per line…"); root.addWidget(self.batch_input)
        br = QHBoxLayout()
        self.system_per_item_checkbox = QCheckBox("Include System Prompt per item"); self.system_per_item_checkbox.setChecked(True); br.addWidget(self.system_per_item_checkbox)
        self.import_btn = QPushButton("📥 Import (CSV/TXT/MD)", clicked=self.import_questions); br.addWidget(self.import_btn)
        self.clear_btn = QPushButton("🧹 Clear Batch", clicked=self.clear_batch); br.addWidget(self.clear_btn)
        br.addWidget(QLabel("Batch Size:")); self.batch_size = QSpinBox(); self.batch_size.setRange(1,10000); self.batch_size.setValue(20); br.addWidget(self.batch_size)
        br.addWidget(QLabel("Delay (ms):")); self.delay_spin = QSpinBox(); self.delay_spin.setRange(0,60000); self.delay_spin.setValue(0); br.addWidget(self.delay_spin)
        self.gen_batch_btn = QPushButton("🧪 Generate Batch → Add to Dataset", clicked=self.generate_batch); br.addWidget(self.gen_batch_btn)
        self.cancel_btn = QPushButton("✋ Cancel", clicked=self.cancel_batch); self.cancel_btn.setEnabled(False); br.addWidget(self.cancel_btn)
        root.addLayout(br)

        # Progress
        pr = QHBoxLayout(); self.progress_bar = QProgressBar(); self.progress_bar.setMinimum(0); self.progress_bar.setMaximum(1); self.progress_bar.setValue(0)
        self.progress_bar.setAlignment(Qt.AlignLeft); pr.addWidget(QLabel("Progress:")); pr.addWidget(self.progress_bar,1)
        self.batch_status = QLabel("-"); pr.addWidget(self.batch_status); root.addLayout(pr)

        # Filter
        fr = QHBoxLayout(); fr.addWidget(QLabel("Filter:")); self.filter_edit = QLineEdit(); self.filter_edit.setPlaceholderText("Type to filter table rows…")
        self.filter_edit.textChanged.connect(self.filter_table); fr.addWidget(self.filter_edit); root.addLayout(fr)

        # Table
        self.table = QTableWidget(); self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["System","User","Assistant","Content Preview"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        root.addWidget(self.table)

        # JSONL preview
        root.addWidget(QLabel("🔎 Live JSONL Preview (selected row)"))
        pv = QHBoxLayout(); self.preview_box = QTextEdit(); self.preview_box.setReadOnly(True); pv.addWidget(self.preview_box)
        pv.addWidget(QPushButton("Copy JSONL", clicked=self.copy_preview)); root.addLayout(pv)

        # Buttons
        btn = QHBoxLayout()
        btn.addWidget(QPushButton("➕ Add to Dataset (single)", clicked=self.add_entry))
        btn.addWidget(QPushButton("💾 Export JSONL", clicked=self.save_jsonl))
        btn.addWidget(QPushButton("📤 Export Table CSV", clicked=self.export_csv))
        btn.addWidget(QPushButton("📂 Load Existing JSONL", clicked=self.load_jsonl))
        btn.addWidget(QPushButton("📄 Clone Last Entry", clicked=self.clone_last))
        btn.addWidget(QPushButton("🌱 Insert Template", clicked=self.insert_template))
        root.addLayout(btn)

        # Stats
        stats_frame = QFrame(); stats_frame.setFrameShape(QFrame.StyledPanel)
        sl = QHBoxLayout(stats_frame); st = QLabel("📈 Dataset Stats"); st.setStyleSheet("font-weight:600;")
        self.stats_label = QLabel("Rows: 0 | Avg tokens: 0 | With system: 0% | Guiding Question: 0% | Avg user chars: 0 | Avg assistant chars: 0")
        sl.addWidget(st); sl.addWidget(self.stats_label, 1, Qt.AlignRight); root.addWidget(stats_frame)

        self.setLayout(root)

        # Init
        self.tokenizer_selector.currentIndexChanged.connect(self.load_tokenizer)
        self.load_tokenizer()

    # Extra tool: sanitize selected rows to neutral
    def sanitize_selected_to_neutral(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if not rows:
            QMessageBox.information(self, "Sanitize", "Select one or more rows."); return
        for r in rows:
            asst_msg = self.table.item(r,2).text() if self.table.item(r,2) else ""
            asst_msg = self.enforce_neutral(asst_msg)
            self.table.setItem(r,2,QTableWidgetItem(asst_msg))
            prev = asst_msg[:100]+"..." if len(asst_msg)>100 else asst_msg
            self.table.setItem(r,3,QTableWidgetItem(prev))
        self.sync_dataset_from_table(); self.refresh_stats()
        QMessageBox.information(self,"Sanitize",f"Neutralized {len(rows)} row(s).")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    builder = JSONLBuilder()
    builder.show()
    sys.exit(app.exec_())
