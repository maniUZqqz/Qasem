"""The architecture rule, enforced by a test instead of a code review.

ROADMAP §8.4: "هیچ Business Logic نباید مستقیم API Call بزند." A rule written
only in a document holds until the first hurried afternoon. This scans the
source of every app and fails the build when something under `apps/` reaches
past `services.ai.gateway` and builds an AI client for itself.

Why it matters and not just as tidiness: the gateway is where a store's data
policy is checked. A task that builds its own client skips that check, and the
way you find out is a customer asking why their messages went to a company in
another country.
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

APPS_DIR = Path(__file__).resolve().parent.parent

# Modules that speak a vendor protocol. Business logic must not import them.
VENDOR_MODULES = {
    "services.ai.ollama",
    "services.ai.openai_compat",
    "services.ai.factory",
    "services.media.api_media",
}

# The error taxonomy lives in the ollama module for historical reasons. Catching
# an exception is not making a call, so these names are importable anywhere.
ALLOWED_NAMES = {
    "OllamaError",
    "OllamaTimeout",
    "OllamaUnavailable",
    "OllamaMalformedOutput",
    "SHORTER_SUFFIX",
}

# Screens whose whole subject is the providers themselves. They configure and
# probe them; they do not process a store's data.
EXEMPT = {
    "ai/admin_providers.py",
    "ai/views_providers.py",
}


def _python_files():
    for path in sorted(APPS_DIR.rglob("*.py")):
        rel = path.relative_to(APPS_DIR).as_posix()
        if "__pycache__" in rel or "/migrations/" in rel:
            continue
        # Tests patch and assert on internals on purpose.
        if path.name.startswith("test"):
            continue
        yield rel, path


def _imports(tree):
    """(module, imported_names) for every import statement in a module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, [alias.name for alias in node.names], node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, [], node.lineno


class AIBoundaryTests(SimpleTestCase):
    def test_apps_do_not_import_vendor_clients(self):
        """No app module builds its own AI client — everything goes via the gateway."""
        offences = []
        for rel, path in _python_files():
            if rel in EXEMPT:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for module, names, lineno in _imports(tree):
                if module not in VENDOR_MODULES:
                    continue
                disallowed = [n for n in names if n not in ALLOWED_NAMES]
                if disallowed or not names:
                    offences.append(
                        f"apps/{rel}:{lineno} → {module} ({', '.join(disallowed) or 'import'})"
                    )
        self.assertEqual(
            offences, [],
            "این‌ها باید از services.ai.gateway استفاده کنند، نه مستقیم از سرویس‌دهنده:\n"
            + "\n".join(offences),
        )

    def test_gateway_entry_points_require_a_store(self):
        """Every public gateway helper takes a store — a call that cannot name
        whose data it carries cannot check whether that store allows it."""
        import inspect

        from services.ai import gateway

        for name in ("text_provider", "vision_provider", "client", "resolve"):
            func = getattr(gateway, name)
            params = list(inspect.signature(func).parameters)
            self.assertIn("store", params, f"gateway.{name} باید فروشگاه بگیرد")
            # and not as an optional afterthought that defaults to "no policy"
            self.assertIs(
                inspect.signature(func).parameters["store"].default,
                inspect.Parameter.empty,
                f"gateway.{name} نباید store اختیاری داشته باشد",
            )

    def test_factory_no_longer_offers_a_storeless_shortcut(self):
        """The old `factory.text_provider()` is gone, not merely discouraged.

        It is the exact call that let a platform-wide provider switch move one
        shop's data without that shop knowing.
        """
        from services.ai import factory

        for gone in ("text_provider", "vision_provider", "provider_for_task"):
            self.assertFalse(
                hasattr(factory, gone),
                f"factory.{gone} باید حذف شده باشد تا کسی دوباره بدون store صدایش نزند",
            )
