# Third-party notices

SimpleBrain itself is MIT-licensed (see `LICENSE`). The packaged builds
(AppImage, installers) also bundle the components below; their license texts
are in `LICENSES/`.

| Component | Version | License | Source |
|---|---|---|---|
| Qt 6 (Core, Gui, Widgets, Svg and related libraries) | 6.11 | LGPL-3.0 | https://download.qt.io/official_releases/qt/ |
| PySide6 (Qt for Python) | 6.11.2 | LGPL-3.0 | https://download.qt.io/official_releases/QtForPython/ |
| Shiboken6 | 6.11.2 | LGPL-3.0 | https://download.qt.io/official_releases/QtForPython/ |
| python-dateutil | 2.9.0.post0 | Apache-2.0 / BSD-3-Clause (dual) | https://github.com/dateutil/dateutil |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six |
| Python runtime | 3.10 | PSF License | https://www.python.org/downloads/source/ |

Qt, PySide6 and Shiboken6 are used under the GNU Lesser General Public
License v3 (`LICENSES/LGPL-3.0.txt`, which builds on `LICENSES/GPL-3.0.txt`).
They are shipped unmodified as separate shared libraries inside the
application folder (`SimpleBrain/_internal/`), so you can replace them with
your own compatible build. Their complete source code is available from the
links above; on request we will provide the exact source for the versions in
any release.

The Linux AppImage also carries system libraries collected from the build
machine (for example GTK and glib, LGPL-2.1+); their sources are available
from the Ubuntu 22.04 archive (https://packages.ubuntu.com/jammy/).
