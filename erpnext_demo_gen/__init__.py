import sys
import time

__version__ = "0.1.0"

# When this process loaded each of the app's modules. A background worker started before the
# app was updated keeps the modules it had loaded, and the jobs it forks inherit them; such a
# job must not run old code next to new (jobs.stale_code_files, design 5.19).
LOADED_AT: dict[str, float] = {__name__: time.time()}


class _ImportClock:
	"""Notes the time each erpnext_demo_gen module is first imported; finds nothing itself."""

	def find_spec(self, name, path=None, target=None):
		if name.startswith(__name__ + "."):
			LOADED_AT[name] = time.time()
		return None


if not any(type(f).__name__ == "_ImportClock" for f in sys.meta_path):
	sys.meta_path.insert(0, _ImportClock())
