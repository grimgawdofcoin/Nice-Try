"""PyInstaller entry point.

A plain top-level script so the frozen app imports `niceclip` as a real
package — freezing niceclip/__main__.py directly runs it without package
context and its relative imports fail.
"""

import multiprocessing

from niceclip.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
