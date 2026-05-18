import os

_this_dir = os.path.dirname(os.path.abspath(__file__))
_source_path = os.path.join(_this_dir, "01_pgn_to_parquet.py")

with open(_source_path, "r", encoding="utf-8") as f:
    source = f.read()

# Execute the original 01_pgn_to_parquet.py contents inside this module's namespace.
# That makes the module importable as pgn_to_parquet, which is required for Windows multiprocessing.
exec(compile(source, _source_path, "exec"), globals())
