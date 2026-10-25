# Vendored OpenEgiz dependency

`extended-api/` is a generated local build cache of the source tree from
https://github.com/ertis-research/extended-api-for-eclipse-ditto
at commit `b49663dea326854a2323423eaeab7e7f54d325a7`, the same commit referenced by
the bundled OpenEgiz Compose deployment. The upstream package.json declares ISC;
that commit contains no separate LICENSE file. Its original metadata is preserved.
The generated cache is excluded from the deliverable and Git. Startup downloads
the pinned archive with SHA256 verification using `prepare_extended_api.py`.

Retrieved from GitHub's codeload tar archive on 2026-10-25. The local build context
avoids Windows Bake path handling and stalled BuildKit remote Git fetching.
The upstream inline Dockerfile and dependency lockfile remain in use.
Archive SHA256: `cf25ac189433d9b1ccd10135498e7379f335ba017460474418d1f4858cc113e3`.
