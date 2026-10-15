/* Autofish.exe: one-click launcher.
 *
 * Next to an unzipped download (Autofish.exe beside an app\ folder) it installs
 * or updates Autofish into %LOCALAPPDATA%\Autofish when that copy is missing or
 * older, then opens the dashboard. The installed copy (no app\ folder beside it)
 * just opens the dashboard. Settings, stats and the webhook are kept on update.
 * Build: python -m ziglang cc -target x86_64-windows-gnu -Os -s -mwindows ...
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

#define TITLE L"Autofish"

static void fail(const wchar_t *message) {
    MessageBoxW(NULL, message, TITLE, MB_OK | MB_ICONERROR);
    ExitProcess(1);
}

static int exists(const wchar_t *path) {
    return GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES;
}

static void read_version(const wchar_t *path, char *out, size_t size) {
    out[0] = 0;
    FILE *file = _wfopen(path, L"rb");
    if (!file) return;
    size_t n = fread(out, 1, size - 1, file);
    fclose(file);
    out[n] = 0;
    while (n && (out[n-1] == '\r' || out[n-1] == '\n' || out[n-1] == ' ')) out[--n] = 0;
}

/* Runs a command and waits. Visible when show is set (the installer), hidden otherwise. */
static DWORD run(wchar_t *command, int show, int wait) {
    STARTUPINFOW startup = {sizeof startup};
    PROCESS_INFORMATION process;
    if (!CreateProcessW(NULL, command, NULL, NULL, FALSE, show ? CREATE_NEW_CONSOLE : CREATE_NO_WINDOW,
                        NULL, NULL, &startup, &process))
        return (DWORD)-1;
    DWORD code = 0;
    if (wait) {
        WaitForSingleObject(process.hProcess, INFINITE);
        GetExitCodeProcess(process.hProcess, &code);
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return code;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    wchar_t self[MAX_PATH], folder[MAX_PATH], local[MAX_PATH], target[MAX_PATH];
    wchar_t source[MAX_PATH], installer[MAX_PATH], path[MAX_PATH], command[4 * MAX_PATH];
    char have[128], want[128];

    if (!GetModuleFileNameW(NULL, self, MAX_PATH)) fail(L"Could not find Autofish.exe on disk.");
    wcscpy(folder, self);
    wchar_t *slash = wcsrchr(folder, L'\\');
    if (slash) *slash = 0;
    if (!GetEnvironmentVariableW(L"LOCALAPPDATA", local, MAX_PATH)) fail(L"LOCALAPPDATA is not set.");
    swprintf(target, MAX_PATH, L"%ls\\Autofish\\app", local);

    swprintf(source, MAX_PATH, L"%ls\\app", folder);
    swprintf(installer, MAX_PATH, L"%ls\\scripts\\Install-Autofish.ps1", source);
    /* The installed copy sits beside its own app folder: nothing to install. */
    if (exists(installer) && _wcsicmp(source, target) != 0) {
        swprintf(path, MAX_PATH, L"%ls\\VERSION", source);
        read_version(path, want, sizeof want);
        swprintf(path, MAX_PATH, L"%ls\\VERSION", target);
        read_version(path, have, sizeof have);
        swprintf(path, MAX_PATH, L"%ls\\.venv\\Scripts\\python.exe", target);
        if (!exists(path) || strcmp(have, want) != 0) {
            swprintf(command, 4 * MAX_PATH,
                     L"powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%ls\" -Launcher \"%ls\" -Pause",
                     installer, self);
            DWORD code = run(command, 1, 1);
            if (code == (DWORD)-1) fail(L"Could not start Windows PowerShell to install Autofish.");
            if (code != 0) fail(L"Autofish could not be installed. The install window shows what went wrong.");
        }
    }

    swprintf(path, MAX_PATH, L"%ls\\scripts\\Open-Autofish.ps1", target);
    if (!exists(path)) fail(L"Autofish is not installed yet. Unzip the download and double-click Autofish.exe there.");
    swprintf(command, 4 * MAX_PATH,
             L"powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%ls\"", path);
    if (run(command, 0, 0) == (DWORD)-1) fail(L"Could not start Windows PowerShell to open Autofish.");
    return 0;
}
