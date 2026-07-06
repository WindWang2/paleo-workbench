# Project Management V1 Design

## Goal

Make the top-level project actions real application workflows instead of static toolbar buttons. The first version covers the project file lifecycle needed by the current workbench:

- create a new empty project
- open an existing `.paleo.json` project
- save the current project
- inspect basic project properties
- refresh all pages after the active project changes

## Current Context

The project model and persistence layer already exist:

- `ProjectDocument` stores metadata, resources, workflow tasks, map documents, quality reports, and export artifacts.
- `ProjectManager` can save and load a project JSON file.
- Resource import/scanning code already accepts an optional `project_path` so imported paths can be stored relative to the project file.

The missing piece is the window-level controller behavior. `HeaderToolbar` renders `新建工程`, `打开工程`, `保存工程`, and `工程属性`, but `PaleoWorkbenchWindow` does not connect those buttons to project lifecycle operations.

## Recommended Approach

Implement a small window-level project controller inside `PaleoWorkbenchWindow`.

This keeps the V1 change close to the existing application structure. A separate controller class can be introduced later if project management grows into autosave, recent projects, collaboration, or command history.

## User-Facing Behavior

### New Project

Clicking `新建工程` creates a fresh `ProjectDocument.new("Untitled Project")`, clears the current project path, rebuilds the shell, and refreshes all pages from the new project state.

V1 does not prompt for project name during creation. The name can remain `Untitled Project` until saved or edited in a later properties workflow.

### Open Project

Clicking `打开工程` opens a file picker for `*.paleo.json`. After selection:

- load the project with `ProjectManager`
- store the selected path as the current project path
- rebuild page state around the loaded project
- update the window title and status bar project name
- leave imported resources and artifacts available in the data page

If loading fails, show an error dialog and keep the existing project active.

### Save Project

Clicking `保存工程` writes the current project with `ProjectManager`.

If the project already has a current path, save to that path. If it does not, show a save dialog and use the selected path.

When saving to a new path, normalize the filename to end in `.paleo.json`.

### Project Properties

Clicking `工程属性` opens a read-only properties dialog for V1. It shows:

- project name
- region
- project file path or `未保存`
- resource count
- export artifact count
- coordinate display CRS
- project version

Editing project metadata is intentionally out of scope for this V1 because it needs dirty-state and validation behavior.

## Application Architecture

`PaleoWorkbenchWindow` will own:

- `self.project`
- `self.project_path: Path | None`
- shell creation and toolbar signal wiring
- project load/save methods callable from tests without file dialogs

Public/testable methods:

- `new_project(name: str = "Untitled Project") -> None`
- `open_project_path(path: str | Path) -> None`
- `save_project() -> Path | None`
- `save_project_as(path: str | Path | None) -> Path | None`
- `project_properties_text() -> str`

Dialog-only helpers stay private:

- `_choose_open_project() -> Path | None`
- `_choose_save_project() -> Path | None`
- `_show_project_error(title: str, message: str) -> None`

## Page Refresh

After a project changes, the app should rebuild or rebind the `AppShell` so every page references the active `ProjectDocument`.

The initial implementation can rebuild the shell because the current app already centralizes page construction in `AppShell`. This avoids stale references in `DataPage`, which holds a project object for import and scan actions.

## Error Handling

Open failures should be non-destructive:

- invalid JSON
- validation errors
- unreadable project file
- missing selected path

The active project remains unchanged if opening fails.

Save failures should show an error dialog and keep the active project in memory.

## Testing

Add focused tests around the controller behavior:

- creating a new project clears `project_path` and updates title/status state
- saving as writes a `.paleo.json` file and stores the active path
- opening a saved project loads resources and refreshes the data page
- saving without an existing path delegates to save-as behavior
- properties text includes project path/resource/artifact counts

The tests should call path-based methods directly and avoid real file dialogs.

## Out of Scope

V1 does not include:

- autosave
- recent projects list
- dirty-state prompts before replacing the current project
- editable project properties
- project templates
- multi-project tabs
- migration UI for old project schema versions

These can be layered on after the basic file lifecycle is reliable.
