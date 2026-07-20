"""
Isolated test environment for running generated Python code safely.

Creates a complete temporary workspace with:
- A dedicated Python virtual environment
- Python code file
- Test file  
- Any required dummy input files
- Proper dependency installation in the venv
"""
from __future__ import annotations

import ast
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from dataclasses import dataclass, field
from pathlib import Path

from cobol_migrator.dummy_files import (
    create_dummy_files,
    generate_dummy_file_specs,
)
from cobol_migrator.safety import UnsafeImportError, check_code_safety, truncate_output

logger = logging.getLogger(__name__)

# Standard library modules that don't need installation
STDLIB_MODULES = {
    "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio", "asyncore",
    "atexit", "audioop", "base64", "bdb", "binascii", "binhex", "bisect",
    "builtins", "bz2", "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd",
    "code", "codecs", "codeop", "collections", "colorsys", "compileall",
    "concurrent", "configparser", "contextlib", "contextvars", "copy", "copyreg",
    "cProfile", "crypt", "csv", "ctypes", "curses", "dataclasses", "datetime",
    "dbm", "decimal", "difflib", "dis", "distutils", "doctest", "email",
    "encodings", "enum", "errno", "faulthandler", "fcntl", "filecmp", "fileinput",
    "fnmatch", "fractions", "ftplib", "functools", "gc", "getopt", "getpass",
    "gettext", "glob", "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac",
    "html", "http", "idlelib", "imaplib", "imghdr", "imp", "importlib", "inspect",
    "io", "ipaddress", "itertools", "json", "keyword", "lib2to3", "linecache",
    "locale", "logging", "lzma", "mailbox", "mailcap", "marshal", "math",
    "mimetypes", "mmap", "modulefinder", "multiprocessing", "netrc", "nis",
    "nntplib", "numbers", "operator", "optparse", "os", "pathlib", "pdb",
    "pickle", "pickletools", "pipes", "pkgutil", "platform", "plistlib", "poplib",
    "posix", "posixpath", "pprint", "profile", "pstats", "pty", "pwd", "py_compile",
    "pyclbr", "pydoc", "queue", "quopri", "random", "re", "readline", "reprlib",
    "resource", "rlcompleter", "runpy", "sched", "secrets", "select", "selectors",
    "shelve", "shlex", "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr",
    "socket", "socketserver", "spwd", "sqlite3", "ssl", "stat", "statistics",
    "string", "stringprep", "struct", "subprocess", "sunau", "symtable", "sys",
    "sysconfig", "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile", "termios",
    "test", "textwrap", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "trace", "traceback", "tracemalloc", "tty", "turtle", "turtledemo",
    "types", "typing", "unicodedata", "unittest", "urllib", "uu", "uuid", "venv",
    "warnings", "wave", "weakref", "webbrowser", "winreg", "winsound", "wsgiref",
    "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    # Built-in constants/modules
    "__future__", "__main__",
}

# Mapping of import names to pip package names (when different)
IMPORT_TO_PACKAGE = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "jwt": "PyJWT",
    "psycopg2": "psycopg2-binary",
    "MySQLdb": "mysqlclient",
    "serial": "pyserial",
    "usb": "pyusb",
    "Crypto": "pycryptodome",
    "lxml": "lxml",
    "numpy": "numpy",
    "pandas": "pandas",
    "requests": "requests",
    "flask": "flask",
    "django": "django",
    "fastapi": "fastapi",
    "sqlalchemy": "sqlalchemy",
    "pytest": "pytest",
    "hypothesis": "hypothesis",
    # Database connectors - use pure Python or binary versions where possible
    "mariadb": "mysql-connector-python",  # mariadb requires libmariadb-dev
    "mysql": "mysql-connector-python",
    "pymysql": "PyMySQL",
    "pg8000": "pg8000",  # pure Python PostgreSQL
    "sqlite3": None,  # stdlib, no install needed
    "cx_Oracle": "oracledb",  # oracledb is pure Python alternative
}

# Packages that require system dependencies and their pure-Python alternatives
# If the alternative is None, we skip installation (it requires system libs)
PACKAGES_WITH_SYSTEM_DEPS = {
    "mariadb": "mysql-connector-python",  # Pure Python MySQL/MariaDB connector
    "mysqlclient": "PyMySQL",  # Pure Python alternative
    "psycopg2": "psycopg2-binary",  # Pre-compiled binary
    "cx_Oracle": "oracledb",  # Pure Python Oracle driver
    "pyodbc": None,  # Requires unixODBC - skip
    "pymssql": None,  # Requires FreeTDS - skip
    "greenlet": "greenlet",  # Usually works but sometimes needs compiler
    "lxml": "lxml",  # Usually has wheels
}


def _extract_imports(code: str) -> set[str]:
    """
    Extract top-level module names from Python code.
    
    Returns set of module names that are imported.
    """
    modules = set()
    
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_module = alias.name.split(".")[0]
                    modules.add(top_module)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_module = node.module.split(".")[0]
                    modules.add(top_module)
    except SyntaxError:
        import_pattern = r'^\s*(?:from\s+(\w+)|import\s+(\w+))'
        for match in re.finditer(import_pattern, code, re.MULTILINE):
            module = match.group(1) or match.group(2)
            if module:
                modules.add(module)
    
    return modules


def _get_required_packages(python_code: str, test_code: str) -> list[str]:
    """
    Determine which packages need to be installed for the code to run.
    
    Filters out standard library modules and local modules, returns pip package names.
    """
    all_imports = _extract_imports(python_code) | _extract_imports(test_code)
    
    # Local modules that are part of the test environment (not pip packages)
    local_modules = {"main", "test_main", "__init__"}
    
    packages_to_install = []
    for module in all_imports:
        if module in STDLIB_MODULES:
            continue
        if module in local_modules:
            continue
        package_name = IMPORT_TO_PACKAGE.get(module, module)
        packages_to_install.append(package_name)
    
    return packages_to_install


def _find_uv_executable() -> str | None:
    """Find the uv executable if available."""
    try:
        result = subprocess.run(
            ["which", "uv"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


@dataclass
class TestEnvironment:
    """Isolated test environment with its own virtual environment."""

    temp_dir: Path
    venv_dir: Path
    python_executable: Path
    main_file: Path
    test_file: Path
    dummy_files: list[str] = field(default_factory=list)
    installed_packages: list[str] = field(default_factory=list)
    _should_cleanup: bool = True

    def cleanup(self) -> None:
        """Remove the temporary directory and all contents including venv."""
        if self._should_cleanup and self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up test environment: {self.temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup test environment: {e}")


@dataclass
class TestResult:
    """Result of test execution."""

    passed: bool
    stdout: str
    stderr: str
    duration_ms: int
    safety_error: str | None = None
    dummy_files_created: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def _create_venv(venv_dir: Path) -> Path:
    """
    Create a virtual environment and return the path to its Python executable.
    
    Uses `uv venv` if available (faster), falls back to standard venv.
    
    Args:
        venv_dir: Directory where the venv will be created
        
    Returns:
        Path to the Python executable in the venv
    """
    logger.info(f"Creating virtual environment at {venv_dir}")
    
    uv_path = _find_uv_executable()
    
    if uv_path:
        # Use uv to create venv (faster and more reliable)
        result = subprocess.run(
            [uv_path, "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning(f"uv venv failed: {result.stderr}, falling back to venv module")
            venv.create(venv_dir, with_pip=False, clear=True)
    else:
        # Fallback to standard venv module
        venv.create(venv_dir, with_pip=False, clear=True)
    
    # Find the Python executable
    if sys.platform == "win32":
        python_path = venv_dir / "Scripts" / "python.exe"
    else:
        python_path = venv_dir / "bin" / "python"
    
    if not python_path.exists():
        raise RuntimeError(f"Failed to create venv: {python_path} not found")
    
    logger.info(f"Virtual environment created with Python at {python_path}")
    return python_path


def _substitute_problematic_packages(packages: list[str]) -> list[str]:
    """
    Replace packages that need system dependencies with pure-Python alternatives.
    """
    result = []
    for pkg in packages:
        pkg_lower = pkg.lower()
        if pkg_lower in PACKAGES_WITH_SYSTEM_DEPS:
            alternative = PACKAGES_WITH_SYSTEM_DEPS[pkg_lower]
            if alternative:
                logger.info(f"Substituting {pkg} with {alternative} (pure Python alternative)")
                result.append(alternative)
            else:
                logger.warning(f"Skipping {pkg} - requires system dependencies with no alternative")
        else:
            result.append(pkg)
    return result


def _install_single_package(
    uv_path: str | None,
    python_executable: Path,
    package: str,
    timeout: int = 60,
) -> bool:
    """Install a single package, return True if successful."""
    try:
        if uv_path:
            result = subprocess.run(
                [uv_path, "pip", "install", "--python", str(python_executable), "--quiet", package],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        else:
            result = subprocess.run(
                [str(python_executable), "-m", "pip", "install", "--quiet", package],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        return result.returncode == 0
    except Exception as e:
        logger.warning(f"Failed to install {package}: {e}")
        return False


def _install_in_venv(
    venv_dir: Path,
    python_executable: Path,
    packages: list[str],
    timeout: int = 180,
) -> tuple[bool, str]:
    """
    Install packages in the virtual environment.
    
    Uses `uv pip` if available (much faster), falls back to pip.
    Automatically substitutes packages that need system dependencies with
    pure-Python alternatives. If batch install fails, tries one-by-one.
    
    Args:
        venv_dir: Path to the virtual environment directory
        python_executable: Path to the venv's Python
        packages: List of package names to install
        timeout: Installation timeout in seconds
    
    Returns:
        Tuple of (success, message)
    """
    # Substitute problematic packages with alternatives
    packages = _substitute_problematic_packages(packages)
    
    # Always install pytest (needed for running tests)
    all_packages = ["pytest"] + [p for p in packages if p and p != "pytest"]
    
    # Remove duplicates while preserving order
    seen = set()
    unique_packages = []
    for p in all_packages:
        if p.lower() not in seen:
            seen.add(p.lower())
            unique_packages.append(p)
    all_packages = unique_packages
    
    if not all_packages:
        return True, "No packages to install"
    
    logger.info(f"Installing packages in venv: {all_packages}")
    
    uv_path = _find_uv_executable()
    
    # Ensure pip is available for non-uv installs
    if not uv_path:
        try:
            subprocess.run(
                [str(python_executable), "-m", "ensurepip", "--upgrade"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception as e:
            logger.warning(f"ensurepip failed: {e}")
    
    try:
        # Try batch install first (faster)
        if uv_path:
            result = subprocess.run(
                [
                    uv_path, "pip", "install", "--python", str(python_executable),
                    "--quiet", *all_packages,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        else:
            result = subprocess.run(
                [
                    str(python_executable), "-m", "pip", "install",
                    "--quiet", "--disable-pip-version-check", *all_packages,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        
        if result.returncode == 0:
            logger.info(f"Successfully installed in venv: {all_packages}")
            return True, f"Installed: {', '.join(all_packages)}"
        
        # Batch failed - try installing one by one
        logger.warning("Batch install failed, trying packages individually...")
        installed = []
        failed = []
        
        for pkg in all_packages:
            if _install_single_package(uv_path, python_executable, pkg, timeout=60):
                installed.append(pkg)
                logger.info(f"Installed: {pkg}")
            else:
                # Try alternative if available
                pkg_lower = pkg.lower()
                if pkg_lower in PACKAGES_WITH_SYSTEM_DEPS:
                    alt = PACKAGES_WITH_SYSTEM_DEPS[pkg_lower]
                    if alt and _install_single_package(uv_path, python_executable, alt, timeout=60):
                        installed.append(f"{alt} (alt for {pkg})")
                        logger.info(f"Installed alternative {alt} for {pkg}")
                        continue
                failed.append(pkg)
                logger.warning(f"Failed to install: {pkg}")
        
        if failed:
            msg = f"Installed: {installed}. Failed: {failed}"
            # Still return True if pytest was installed (tests can run)
            if "pytest" in installed:
                return True, msg
            return False, msg
        
        return True, f"Installed (individually): {', '.join(installed)}"
            
    except subprocess.TimeoutExpired:
        logger.warning(f"Package installation timed out after {timeout}s")
        return False, f"Installation timed out after {timeout} seconds"
    except Exception as e:
        logger.exception(f"Error installing packages in venv: {e}")
        return False, f"Installation error: {e}"


def _get_safe_env(venv_dir: Path) -> dict[str, str]:
    """
    Get environment variables for safe subprocess execution in the venv.
    """
    env = os.environ.copy()
    
    # Set VIRTUAL_ENV
    env["VIRTUAL_ENV"] = str(venv_dir)
    
    # Update PATH to prioritize venv binaries
    if sys.platform == "win32":
        venv_bin = venv_dir / "Scripts"
    else:
        venv_bin = venv_dir / "bin"
    
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
    
    # Remove PYTHONHOME if set (can interfere with venv)
    env.pop("PYTHONHOME", None)
    
    # Ensure UTF-8 encoding
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    
    return env


def create_test_environment(
    python_code: str,
    test_code: str,
    cobol_source: str | None = None,
    io_contract: dict | None = None,
    create_dummy_files_flag: bool = False,
    program_summary: str | None = None,
) -> tuple[TestEnvironment | None, str | None]:
    """
    Create an isolated test environment with its own virtual environment.
    
    ALWAYS creates a virtual environment for proper isolation and installs
    all required dependencies. This ensures tests run in a clean environment
    with all necessary modules available.
    
    Args:
        python_code: The generated Python code to test
        test_code: The pytest test code
        cobol_source: Original COBOL source (for dummy file generation)
        io_contract: I/O contract from analysis (for dummy file generation)
        create_dummy_files_flag: Whether to create dummy input files
    
    Returns:
        Tuple of (TestEnvironment, error_message).
        If error_message is not None, TestEnvironment will be None.
    """
    temp_dir = None
    try:
        # Create test environment under project test_runs/ directory for organized logging
        project_test_runs = Path(__file__).resolve().parent.parent.parent / "test_runs"
        project_test_runs.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="run_", dir=project_test_runs))
        logger.info(f"Created test environment: {temp_dir}")
        
        # Create src directory for code files
        src_dir = temp_dir / "src"
        src_dir.mkdir()
        
        # Write main Python file
        main_file = src_dir / "main.py"
        main_file.write_text(python_code)
        
        # Write test file
        test_file = src_dir / "test_main.py"
        test_file.write_text(test_code)
        
        # Create __init__.py
        init_file = src_dir / "__init__.py"
        init_file.write_text("")
        
        dummy_files: list[str] = []
        installed_packages: list[str] = []
        venv_dir = temp_dir / "venv"
        
        # ALWAYS create virtual environment for proper isolation
        python_executable = _create_venv(venv_dir)
        
        # Create dummy files if requested
        if create_dummy_files_flag and cobol_source:
            specs = generate_dummy_file_specs(
                cobol_source, python_code, io_contract, program_summary,
            )
            if specs:
                result = create_dummy_files(specs, src_dir)
                if result.success:
                    dummy_files = result.files_created
                    logger.info(f"Created {len(dummy_files)} dummy files")
                else:
                    logger.warning(f"Failed to create dummy files: {result.error}")
        
        # ALWAYS install pytest and any detected dependencies
        packages = _get_required_packages(python_code, test_code)
        success, msg = _install_in_venv(venv_dir, python_executable, packages)
        if success:
            installed_packages = ["pytest"] + packages
            logger.info(f"Installed packages: {installed_packages}")
        else:
            logger.warning(f"Package installation warning: {msg}")
            # Still record what we tried to install
            installed_packages = ["pytest"] + packages
        
        env = TestEnvironment(
            temp_dir=temp_dir,
            venv_dir=venv_dir,
            python_executable=python_executable,
            main_file=main_file,
            test_file=test_file,
            dummy_files=dummy_files,
            installed_packages=installed_packages,
        )
        
        return env, None
        
    except Exception as e:
        logger.exception(f"Failed to create test environment: {e}")
        # Clean up on failure
        if temp_dir and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
        return None, str(e)


def run_tests_in_environment(
    env: TestEnvironment,
    python_code: str,
    timeout: int = 60,
    max_install_retries: int = 2,
) -> TestResult:
    """
    Run tests in the isolated environment using the venv's Python.
    
    If tests fail due to missing modules, automatically installs them and retries.
    
    Args:
        env: The test environment to use
        python_code: The Python code (for safety check)
        timeout: Maximum execution time in seconds
        max_install_retries: Maximum number of times to retry after installing modules
    
    Returns:
        TestResult with execution details
    """
    issues: list[str] = []
    
    # Safety check first
    try:
        check_code_safety(python_code)
    except UnsafeImportError as e:
        return TestResult(
            passed=False,
            stdout="",
            stderr=f"SAFETY CHECK FAILED: {e}",
            duration_ms=0,
            safety_error=str(e),
            issues=[f"Code contains unsafe imports: {e}"],
        )
    
    start_time = time.perf_counter()
    src_dir = env.main_file.parent
    
    # Prepare environment variables
    if env.venv_dir.exists():
        safe_env = _get_safe_env(env.venv_dir)
    else:
        safe_env = os.environ.copy()
        safe_env["LANG"] = "C.UTF-8"
        safe_env["LC_ALL"] = "C.UTF-8"
    
    # Add src directory to PYTHONPATH
    existing_pythonpath = safe_env.get("PYTHONPATH", "")
    if existing_pythonpath:
        safe_env["PYTHONPATH"] = f"{src_dir}:{existing_pythonpath}"
    else:
        safe_env["PYTHONPATH"] = str(src_dir)
    
    stdout = ""
    stderr = ""
    passed = False
    installed_on_retry: list[str] = []
    
    for attempt in range(max_install_retries + 1):
        try:
            # Run pytest using the venv's Python
            result = subprocess.run(
                [
                    str(env.python_executable),
                    "-m",
                    "pytest",
                    "-v",
                    "--tb=short",
                    "-x",  # Stop on first failure
                    str(env.test_file),
                ],
                cwd=str(src_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=safe_env,
            )
            
            passed = result.returncode == 0
            stdout = truncate_output(result.stdout)
            stderr = truncate_output(result.stderr)
            
            if passed:
                break
            
            # Check if failure was due to missing modules
            missing_modules = _extract_missing_modules(result.stdout, result.stderr)
            
            if missing_modules and attempt < max_install_retries and env.venv_dir.exists():
                logger.info(f"Test failed due to missing modules: {missing_modules}, installing...")
                success, msg = _install_in_venv(
                    env.venv_dir,
                    env.python_executable,
                    missing_modules,
                    timeout=120,
                )
                if success:
                    installed_on_retry.extend(missing_modules)
                    logger.info(f"Installed {missing_modules}, retrying tests...")
                    continue
                else:
                    logger.warning(f"Failed to install {missing_modules}: {msg}")
                    issues.append(f"Failed to install required modules: {', '.join(missing_modules)}")
                    break
            else:
                # Not a missing module issue, or out of retries
                break
                
        except subprocess.TimeoutExpired:
            passed = False
            stdout = ""
            stderr = f"TEST TIMEOUT: Execution exceeded {timeout} seconds"
            issues.append(f"Test execution timed out after {timeout} seconds")
            break
            
        except FileNotFoundError as e:
            passed = False
            stdout = ""
            stderr = f"EXECUTION ERROR: {e}"
            issues.append(f"Missing executable or file: {e}")
            break
            
        except Exception as e:
            passed = False
            stdout = ""
            stderr = f"TEST EXECUTION ERROR: {e}"
            issues.append(f"Unexpected error during test execution: {e}")
            break
    
    if not passed and not issues:
        issues.extend(_analyze_test_output(stdout, stderr))
    
    if installed_on_retry:
        env.installed_packages.extend(installed_on_retry)
        logger.info(f"Additional packages installed on retry: {installed_on_retry}")
    
    duration_ms = int((time.perf_counter() - start_time) * 1000)
    
    return TestResult(
        passed=passed,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        dummy_files_created=env.dummy_files,
        issues=issues,
    )


def _extract_missing_modules(stdout: str, stderr: str) -> list[str]:
    """
    Extract names of missing modules from test output.
    
    Returns list of module/package names that need to be installed.
    """
    combined = f"{stdout}\n{stderr}"
    missing = []
    
    # Pattern: ModuleNotFoundError: No module named 'xxx'
    for match in re.finditer(r"no module named ['\"]?(\w+)", combined, re.IGNORECASE):
        module = match.group(1)
        if module not in STDLIB_MODULES and module not in {"main", "test_main"}:
            # Map import name to package name if needed
            package = IMPORT_TO_PACKAGE.get(module, module)
            if package not in missing:
                missing.append(package)
    
    # Pattern: ImportError: cannot import name 'xxx' from 'yyy'
    for match in re.finditer(r"cannot import name .+ from ['\"]?(\w+)", combined, re.IGNORECASE):
        module = match.group(1)
        if module not in STDLIB_MODULES and module not in {"main", "test_main"}:
            package = IMPORT_TO_PACKAGE.get(module, module)
            if package not in missing:
                missing.append(package)
    
    return missing


def _analyze_test_output(stdout: str, stderr: str) -> list[str]:
    """
    Analyze test output to identify specific issues.
    """
    issues = []
    combined = f"{stdout}\n{stderr}".lower()
    
    if "filenotfounderror" in combined or "no such file or directory" in combined:
        issues.append("Test requires external files that are not available")
    
    if "modulenotfounderror" in combined or "no module named" in combined:
        missing = _extract_missing_modules(stdout, stderr)
        if missing:
            issues.append(f"Missing Python module(s): {', '.join(missing)}")
        else:
            issues.append("Missing required Python module")
    
    if "connectionerror" in combined or "connection refused" in combined:
        issues.append("Test requires network/database connection")
    
    if "permissionerror" in combined or "permission denied" in combined:
        issues.append("Insufficient permissions for file/resource access")
    
    if "assertionerror" in combined:
        issues.append("Test assertion failed - output may not match expected values")
    
    if "timeout" in combined:
        issues.append("Operation timed out during test execution")
    
    if "syntaxerror" in combined:
        issues.append("Generated code contains syntax errors")
    
    if "nameerror" in combined:
        issues.append("Generated code references undefined variables")
    
    if "typeerror" in combined:
        issues.append("Type mismatch in generated code")
    
    if "importerror" in combined:
        issues.append("Failed to import required module")
    
    if not issues:
        if "failed" in combined or "error" in combined:
            issues.append("Test execution failed - see output for details")
    
    return issues


def run_isolated_tests(
    python_code: str,
    test_code: str,
    cobol_source: str | None = None,
    io_contract: dict | None = None,
    create_dummy_files_flag: bool = False,
    timeout: int = 60,
    cleanup_on_success: bool = True,
    program_summary: str | None = None,
) -> TestResult:
    """
    High-level function to run tests in a complete isolated environment.
    
    When create_dummy_files_flag is True:
    - Creates a dedicated virtual environment
    - Installs pytest and required packages in the venv
    - Creates dummy input files
    - Runs tests using the venv's Python
    - Cleans up everything on success
    
    Args:
        python_code: Generated Python code to test
        test_code: Pytest test code
        cobol_source: Original COBOL source
        io_contract: I/O contract from analysis
        create_dummy_files_flag: Whether to create venv, dummy files, install deps
        timeout: Test timeout in seconds
        cleanup_on_success: Whether to cleanup temp dir on successful tests
    
    Returns:
        TestResult with complete execution details
    """
    env, error = create_test_environment(
        python_code=python_code,
        test_code=test_code,
        cobol_source=cobol_source,
        io_contract=io_contract,
        create_dummy_files_flag=create_dummy_files_flag,
        program_summary=program_summary,
    )
    
    if error or env is None:
        return TestResult(
            passed=False,
            stdout="",
            stderr=f"Failed to create test environment: {error}",
            duration_ms=0,
            issues=[f"Environment setup failed: {error}"],
        )
    
    try:
        result = run_tests_in_environment(env, python_code, timeout)
        
        # Cleanup on success, keep on failure for debugging
        if result.passed and cleanup_on_success:
            env.cleanup()
        elif not result.passed:
            logger.info(f"Keeping test environment for debugging: {env.temp_dir}")
            env._should_cleanup = False
        
        return result
        
    except Exception as e:
        logger.exception(f"Error running isolated tests: {e}")
        env.cleanup()
        return TestResult(
            passed=False,
            stdout="",
            stderr=f"Test execution error: {e}",
            duration_ms=0,
            issues=[f"Test execution error: {e}"],
        )
