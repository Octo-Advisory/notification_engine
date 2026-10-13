from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = [line.strip() for line in f.read().splitlines() if line.strip()]

with open("notification_engine/__init__.py") as f:
	# very small __init__, so just default a version if not found
	version = "0.0.1"
	for line in f.read().splitlines():
		if line.startswith("__version__"):
			version = line.split("=")[1].strip().strip('"').strip("'")

setup(
	name="notification_engine",
	version=version,
	description="Generic, user-level notification engine for Frappe / ERPNext",
	author="Your Company",
	author_email="dev@example.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires,
)
