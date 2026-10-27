"""book_pipeline —— EPUB/PDF 书 → 逐页 PNG → 分段笔记 → 整合文档的独立脚本区。

这些脚本不依赖 IAF 引擎，可以单独运行；run_books.py 通过 import 调用
convert()、build_chunks() 与 merge()。
"""
