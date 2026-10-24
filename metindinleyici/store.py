# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Kalıcı veri katmanı (SQLite).

Belgeler, dosya yoluna göre değil içerik kimliğine (extract.document_id) göre tutulur.
Sonraki aşamalarda kütüphane, alıntılar, notlar, etiketler ve telaffuz sözlüğü de bu
veritabanına eklenecek; şema sürümü `meta` tablosunda saklanır ve sırayla yükseltilir.
"""
import json
import os
import sqlite3
import time

SCHEMA_VERSION = 4

_MIGRATIONS = {
    1: """
        CREATE TABLE IF NOT EXISTS documents (
            id              TEXT PRIMARY KEY,
            path            TEXT NOT NULL,
            title           TEXT,
            ext             TEXT,
            size            INTEGER,
            added_at        REAL,
            last_opened     REAL,
            position        INTEGER DEFAULT 0,
            position_anchor TEXT,
            sentence_count  INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path);
    """,
    2: """
        CREATE TABLE IF NOT EXISTS pron_rules (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            position       INTEGER NOT NULL DEFAULT 0,
            pattern        TEXT NOT NULL,
            replacement    TEXT NOT NULL DEFAULT '',
            kind           TEXT NOT NULL DEFAULT 'word',
            case_sensitive INTEGER NOT NULL DEFAULT 0,
            enabled        INTEGER NOT NULL DEFAULT 1,
            doc_id         TEXT,
            exceptions     TEXT NOT NULL DEFAULT '[]',
            note           TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS doc_edits (
            doc_id      TEXT PRIMARY KEY,
            sections    TEXT NOT NULL,
            opts        TEXT NOT NULL,
            updated_at  REAL,
            edit_count  INTEGER NOT NULL DEFAULT 0
        );
    """,
    3: """
        ALTER TABLE documents ADD COLUMN pages INTEGER;
        ALTER TABLE documents ADD COLUMN pages_approx INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE documents ADD COLUMN author TEXT NOT NULL DEFAULT '';
        ALTER TABLE documents ADD COLUMN meta_title TEXT NOT NULL DEFAULT '';
        ALTER TABLE documents ADD COLUMN custom_title TEXT NOT NULL DEFAULT '';
        ALTER TABLE documents ADD COLUMN in_library INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE documents ADD COLUMN info_done INTEGER NOT NULL DEFAULT 0;
    """,
    4: """
        ALTER TABLE documents ADD COLUMN year TEXT NOT NULL DEFAULT '';
        ALTER TABLE documents ADD COLUMN publisher TEXT NOT NULL DEFAULT '';
        ALTER TABLE documents ADD COLUMN city TEXT NOT NULL DEFAULT '';
        ALTER TABLE documents ADD COLUMN page_offset INTEGER NOT NULL DEFAULT 0;
        CREATE TABLE IF NOT EXISTS annotations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id      TEXT NOT NULL,
            kind        TEXT NOT NULL,              -- quote | note | highlight
            text        TEXT NOT NULL,              -- kaynaktaki metin
            note        TEXT NOT NULL DEFAULT '',   -- kullanıcının kendi yazdığı
            anchor      TEXT,                       -- ilk cümlenin izi
            sent_index  INTEGER,
            sent_count  INTEGER NOT NULL DEFAULT 1,
            page_label  TEXT NOT NULL DEFAULT '',
            color       TEXT,
            created_at  REAL,
            updated_at  REAL
        );
        CREATE INDEX IF NOT EXISTS idx_ann_doc ON annotations(doc_id);
        CREATE TABLE IF NOT EXISTS tags (
            annotation_id INTEGER NOT NULL REFERENCES annotations(id) ON DELETE CASCADE,
            tag           TEXT NOT NULL,
            PRIMARY KEY (annotation_id, tag)
        );
        CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
    """,
}


class Store:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")       # yazarken okumayı kilitlemez, çökmeye dayanıklı
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self._migrate()

    def _migrate(self):
        row = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        current = int(row["value"]) if row else 0
        for v in range(current + 1, SCHEMA_VERSION + 1):
            with self.db:
                self.db.executescript(_MIGRATIONS[v])
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(v),))

    def close(self):
        try:
            self.db.close()
        except Exception:
            pass

    # ── belgeler ──
    def get_document(self, doc_id):
        return self.db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()

    def open_document(self, doc_id, path, sentence_count):
        """Belge açıldığında kaydı oluşturur ya da günceller (yeni yol, son açılma zamanı)."""
        now = time.time()
        title = os.path.splitext(os.path.basename(path))[0]
        ext = os.path.splitext(path)[1].lower()
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
        with self.db:
            self.db.execute(
                """INSERT INTO documents (id, path, title, ext, size, added_at, last_opened, sentence_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET path=excluded.path, ext=excluded.ext, size=excluded.size,
                       last_opened=excluded.last_opened, sentence_count=excluded.sentence_count, in_library=1""",
                (doc_id, os.path.abspath(path), title, ext, size, now, now, sentence_count))
        return self.get_document(doc_id)

    def set_position(self, doc_id, index, anchor):
        with self.db:
            self.db.execute("UPDATE documents SET position=?, position_anchor=? WHERE id=?",
                            (index, anchor, doc_id))

    # ── telaffuz sözlüğü ──
    def meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))

    def load_rules(self):
        from .pronounce import Rule
        out = []
        for r in self.db.execute("SELECT * FROM pron_rules ORDER BY position, id"):
            try:
                exc = json.loads(r["exceptions"] or "[]")
            except ValueError:
                exc = []
            out.append(Rule(pattern=r["pattern"], replacement=r["replacement"], kind=r["kind"],
                            case_sensitive=bool(r["case_sensitive"]), enabled=bool(r["enabled"]),
                            doc_id=r["doc_id"], exceptions=exc, note=r["note"], id=r["id"],
                            position=r["position"]))
        return out

    def save_rules(self, rules):
        """Sözlüğü sırasıyla birlikte bütün olarak yazar (kurallar az olduğu için en güvenli yol)."""
        with self.db:
            self.db.execute("DELETE FROM pron_rules")
            for k, r in enumerate(rules):
                self.db.execute(
                    """INSERT INTO pron_rules (position, pattern, replacement, kind, case_sensitive, enabled,
                                               doc_id, exceptions, note) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (k, r.pattern, r.replacement, r.kind, int(r.case_sensitive), int(r.enabled), r.doc_id,
                     json.dumps(r.exceptions, ensure_ascii=False), r.note))

    # ── elle düzeltilmiş metinler ──
    def get_edits(self, doc_id):
        row = self.db.execute("SELECT * FROM doc_edits WHERE doc_id=?", (doc_id,)).fetchone()
        if not row:
            return None
        try:
            return {"sections": [(lbl, paras) for lbl, paras in json.loads(row["sections"])],
                    "opts": json.loads(row["opts"]), "updated_at": row["updated_at"],
                    "edit_count": row["edit_count"]}
        except (ValueError, TypeError):
            return None

    def save_edits(self, doc_id, sections, opts):
        with self.db:
            self.db.execute(
                """INSERT INTO doc_edits (doc_id, sections, opts, updated_at, edit_count) VALUES (?,?,?,?,1)
                   ON CONFLICT(doc_id) DO UPDATE SET sections=excluded.sections, opts=excluded.opts,
                       updated_at=excluded.updated_at, edit_count=doc_edits.edit_count + 1""",
                (doc_id, json.dumps(sections, ensure_ascii=False), json.dumps(opts, sort_keys=True), time.time()))

    def delete_edits(self, doc_id):
        with self.db:
            self.db.execute("DELETE FROM doc_edits WHERE doc_id=?", (doc_id,))

    # ── kütüphane ──
    def library(self):
        return self.db.execute("SELECT * FROM documents WHERE in_library=1").fetchall()

    def add_to_library(self, doc_id, path):
        """Belgeyi açmadan kütüphaneye ekler. Dönüş: 'new' | 'restored' | 'moved' | 'exists'."""
        row = self.get_document(doc_id)
        path = os.path.abspath(path)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
        if row is None:
            with self.db:
                self.db.execute(
                    """INSERT INTO documents (id, path, title, ext, size, added_at, in_library)
                       VALUES (?, ?, ?, ?, ?, ?, 1)""",
                    (doc_id, path, os.path.splitext(os.path.basename(path))[0],
                     os.path.splitext(path)[1].lower(), size, time.time()))
            return "new"
        state = "exists"
        if not row["in_library"]:
            state = "restored"
        elif os.path.normcase(row["path"]) != os.path.normcase(path) and not os.path.exists(row["path"]):
            state = "moved"
        if state != "exists" or os.path.normcase(row["path"]) != os.path.normcase(path):
            if os.path.exists(row["path"]) and os.path.normcase(row["path"]) != os.path.normcase(path) \
                    and row["in_library"]:
                return "exists"                     # aynı belgenin başka bir kopyası: ilkini koru
            with self.db:
                self.db.execute("UPDATE documents SET path=?, in_library=1, size=COALESCE(?, size) WHERE id=?",
                                (path, size, doc_id))
        return state

    def set_info(self, doc_id, info):
        with self.db:
            self.db.execute("""UPDATE documents SET pages=?, pages_approx=?, author=CASE WHEN author='' THEN ?
                               ELSE author END, meta_title=?, info_done=1 WHERE id=?""",
                            (info.get("pages"), int(bool(info.get("pages_approx"))), info.get("author") or "",
                             info.get("meta_title") or "", doc_id))

    def set_details(self, doc_id, custom_title, author, year=None, publisher=None, city=None, page_offset=None):
        row = self.get_document(doc_id)
        if row is None:
            return
        with self.db:
            self.db.execute(
                "UPDATE documents SET custom_title=?, author=?, year=?, publisher=?, city=?, page_offset=? WHERE id=?",
                (custom_title.strip(), author.strip(),
                 (row["year"] if year is None else year).strip(),
                 (row["publisher"] if publisher is None else publisher).strip(),
                 (row["city"] if city is None else city).strip(),
                 int(row["page_offset"] if page_offset is None else page_offset), doc_id))

    def set_path(self, doc_id, path):
        with self.db:
            self.db.execute("UPDATE documents SET path=?, title=? WHERE id=?",
                            (os.path.abspath(path), os.path.splitext(os.path.basename(path))[0], doc_id))

    def remove_from_library(self, doc_id):
        """Kütüphane listesinden çıkarır; kaldığınız yer ve düzeltmeler saklı kalır, dosya yeniden
        açılırsa belge kütüphaneye geri döner."""
        with self.db:
            self.db.execute("UPDATE documents SET in_library=0 WHERE id=?", (doc_id,))

    # ── alıntılar, notlar, vurgular ──
    _ANN_SELECT = """
        SELECT a.*, d.title AS doc_title, d.custom_title, d.author, d.path, d.page_offset, d.year,
               d.publisher, d.city, d.ext,
               (SELECT group_concat(tag, ' ') FROM tags WHERE annotation_id = a.id) AS tags
        FROM annotations a LEFT JOIN documents d ON d.id = a.doc_id
    """

    def add_annotation(self, doc_id, kind, text, note="", anchor=None, index=None, count=1, page_label="",
                       color=None, tags=()):
        now = time.time()
        with self.db:
            cur = self.db.execute(
                """INSERT INTO annotations (doc_id, kind, text, note, anchor, sent_index, sent_count, page_label,
                                            color, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (doc_id, kind, text, note, anchor, index, count, page_label, color, now, now))
            aid = cur.lastrowid
            self._set_tags(aid, tags)
        return aid

    def _set_tags(self, aid, tags):
        self.db.execute("DELETE FROM tags WHERE annotation_id=?", (aid,))
        for t in dict.fromkeys(t for t in tags if t):
            self.db.execute("INSERT OR IGNORE INTO tags VALUES (?, ?)", (aid, t))

    def update_annotation(self, aid, note=None, tags=None, page_label=None, kind=None):
        with self.db:
            if note is not None:
                self.db.execute("UPDATE annotations SET note=?, updated_at=? WHERE id=?", (note, time.time(), aid))
            if page_label is not None:
                self.db.execute("UPDATE annotations SET page_label=?, updated_at=? WHERE id=?",
                                (page_label, time.time(), aid))
            if kind is not None:
                self.db.execute("UPDATE annotations SET kind=?, updated_at=? WHERE id=?", (kind, time.time(), aid))
            if tags is not None:
                self._set_tags(aid, tags)

    def delete_annotations(self, ids):
        with self.db:
            self.db.executemany("DELETE FROM annotations WHERE id=?", [(i,) for i in ids])

    def annotations(self, doc_id=None, ids=None):
        q, args = self._ANN_SELECT, []
        if ids is not None:
            q += f" WHERE a.id IN ({','.join('?' * len(ids))})"
            args = list(ids)
        elif doc_id is not None:
            q += " WHERE a.doc_id = ?"
            args = [doc_id]
        q += " ORDER BY a.doc_id, a.sent_index, a.created_at"
        return self.db.execute(q, args).fetchall() if ids is None or ids else []

    def find_annotation(self, doc_id, kind, anchor):
        return self.db.execute("SELECT * FROM annotations WHERE doc_id=? AND kind=? AND anchor=?",
                               (doc_id, kind, anchor)).fetchone()

    def all_tags(self):
        return self.db.execute("SELECT tag, count(*) AS n FROM tags GROUP BY tag ORDER BY n DESC, tag").fetchall()

    # ── temizlik ──
    def cleanup_counts(self):
        q = lambda sql: self.db.execute(sql).fetchone()[0]
        out_docs = "SELECT id FROM documents WHERE in_library=0"
        return {
            "docs_out": q("SELECT count(*) FROM documents WHERE in_library=0"),
            "ann_out": q(f"SELECT count(*) FROM annotations WHERE doc_id IN ({out_docs}) "
                         "OR doc_id NOT IN (SELECT id FROM documents)"),
            "edits_out": q(f"SELECT count(*) FROM doc_edits WHERE doc_id IN ({out_docs})"),
            "annotations": q("SELECT count(*) FROM annotations"),
            "edits": q("SELECT count(*) FROM doc_edits"),
            "rules": q("SELECT count(*) FROM pron_rules"),
        }

    def purge_outside_library(self):
        """Kütüphanede olmayan belgelerin bütün kayıtlarını siler (kaldığınız yer, düzeltmeler, alıntılar)."""
        out_docs = "SELECT id FROM documents WHERE in_library=0"
        with self.db:
            self.db.execute(f"DELETE FROM annotations WHERE doc_id IN ({out_docs}) "
                            "OR doc_id NOT IN (SELECT id FROM documents)")
            self.db.execute(f"DELETE FROM doc_edits WHERE doc_id IN ({out_docs})")
            self.db.execute(f"DELETE FROM pron_rules WHERE doc_id IS NOT NULL AND doc_id IN ({out_docs})")
            self.db.execute("DELETE FROM documents WHERE in_library=0")

    def clear_annotations(self):
        with self.db:
            self.db.execute("DELETE FROM annotations")

    def clear_edits(self):
        with self.db:
            self.db.execute("DELETE FROM doc_edits")

    def reset_info(self):
        """Kapaklar silindikten sonra kütüphane bilgileri yeniden hazırlansın."""
        with self.db:
            self.db.execute("UPDATE documents SET info_done=0")

    def missing_in_library(self):
        return [r for r in self.library() if not os.path.exists(r["path"])]

    def vacuum(self):
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.execute("VACUUM")

    def file_size(self):
        return sum(os.path.getsize(self.path + ext) for ext in ("", "-wal", "-shm") if os.path.exists(self.path + ext))
