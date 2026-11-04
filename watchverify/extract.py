"""Video file to Procedure JSON through Spark (video with its audio, strict schema)."""
import json
from pathlib import Path
from . import schema
from .meta_client import MetaClient


async def extract(client: MetaClient, video: Path, run_dir: Path, name: str = "reference",
                  max_output_tokens: int = 6000) -> dict:
    fid = await client.upload(video, f"{name}.upload")
    proc, usage = await client.structured(
        f"{name}.procedure", "procedure", schema.PROCEDURE, schema.EXTRACT_INSTRUCTIONS,
        [{"type": "input_text", "text": schema.EXTRACT_PROMPT}, {"type": "input_file", "file_id": fid}],
        max_output_tokens=max_output_tokens)
    proc["_source"] = dict(video=str(video), file_id=fid, usage=usage)
    problems = schema.validate_procedure(proc)
    if problems:
        proc["_problems"] = problems
    out = Path(run_dir) / f"{name}.procedure.json"
    out.write_text(json.dumps(proc, indent=1))
    return proc
