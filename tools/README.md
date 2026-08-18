# Repository tools

Put repository-wide automation here once it is substantial enough to test and
reuse. Small Python helpers should initially live in the main package so they
share its type checks, tests, and lockfile.

This directory is intentionally **not** a separate uv workspace member. uv
workspaces are useful when the repository contains multiple independently
packaged, interconnected Python projects. Adding one for a collection of scripts
would create another packaging boundary without buying isolation or reuse.

If a future ingestion SDK, application, or release utility becomes a real
package, add it as a workspace member and keep the single repository lockfile.
