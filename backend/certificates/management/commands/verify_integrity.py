"""
Recompute what was hashed when it was signed or stored. A difference means a record
or a file was changed behind the application. Schedule it daily: it fails loudly.
"""
import hashlib

from django.core.management.base import BaseCommand, CommandError

from audit.services import record
from batches.models import BatchDocument
from certificates.models import Certificate
from certificates.services import integrity_problems
from execution.models import Attachment


def _file_problem(stored, label: str) -> str:
    digest = hashlib.sha256()
    try:
        with stored.file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except (FileNotFoundError, OSError):
        return f"{label}: the file is missing"
    return "" if digest.hexdigest() == stored.sha256 else f"{label}: the file has changed"


class Command(BaseCommand):
    help = "Check every certificate, signature and stored file against its hash."

    def handle(self, *args, **options):
        problems = []
        certificates = Certificate.objects.select_related("sample").prefetch_related("signatures")
        for cert in certificates.iterator(chunk_size=500):
            problems += [f"{cert.sample.sample_no} v{cert.version}: {p}" for p in integrity_problems(cert)]
        files = 0
        for model, label in ((Attachment, "attachment"), (BatchDocument, "batch document")):
            for stored in model.objects.iterator(chunk_size=500):
                files += 1
                problem = _file_problem(stored, f"{label} {stored.pk}")
                if problem:
                    problems.append(problem)
        record(None, "INTEGRITY_CHECK", "system", "all", certificates=certificates.count(), files=files,
               problems=problems[:50])
        if problems:
            raise CommandError("Integrity check failed:\n" + "\n".join(problems))
        self.stdout.write(f"{certificates.count()} certificates and {files} files match what was signed and stored.")
