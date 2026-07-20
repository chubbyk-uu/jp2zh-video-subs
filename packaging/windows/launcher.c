#include <windows.h>
#include <wchar.h>

#include "launcher_resources.h"

static HINSTANCE launcher_instance;

static const wchar_t *fallback_string(UINT id) {
    switch (id) {
        case IDS_APP_TITLE: return L"jp2zh Subtitle Tool";
        case IDS_ERROR_EXE_DIR: return L"Could not determine the application folder.";
        case IDS_ERROR_INVALID_PATH: return L"The launcher path is invalid.";
        case IDS_ERROR_PATH_TOO_LONG: return L"The portable folder path is too long.";
        case IDS_ERROR_INCOMPLETE: return L"The portable folder is incomplete: embedded Python or the GUI script is missing.";
        case IDS_ERROR_ENVIRONMENT: return L"Could not initialise the portable runtime environment.";
        case IDS_ERROR_START_FORMAT: return L"Could not start the GUI (Windows error %lu).";
        case IDS_ERROR_START_GENERIC: return L"Could not start the GUI.";
        default: return L"jp2zh Subtitle Tool";
    }
}

static const wchar_t *load_string(UINT id, wchar_t *buffer, int capacity) {
    return LoadStringW(launcher_instance, id, buffer, capacity) > 0 ? buffer : fallback_string(id);
}

static void show_error(UINT message_id) {
    wchar_t title[128];
    wchar_t message[512];
    MessageBoxW(
        NULL,
        load_string(message_id, message, 512),
        load_string(IDS_APP_TITLE, title, 128),
        MB_ICONERROR
    );
}

static int join_path(wchar_t *output, size_t capacity, const wchar_t *root, const wchar_t *relative) {
    int written = swprintf(output, capacity, L"%ls\\%ls", root, relative);
    return written >= 0 && (size_t)written < capacity;
}

static int set_root_environment(const wchar_t *root) {
    wchar_t value[32768];
    wchar_t system_root[MAX_PATH];
    DWORD system_root_length;
    int written;

    system_root_length = GetEnvironmentVariableW(L"SystemRoot", system_root, MAX_PATH);
    if (system_root_length == 0 || system_root_length >= MAX_PATH) {
        return 0;
    }

    if (!SetEnvironmentVariableW(L"JP2ZH_PORTABLE_ROOT", root) ||
        !SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1") ||
        !SetEnvironmentVariableW(L"PYTHONDONTWRITEBYTECODE", L"1") ||
        !SetEnvironmentVariableW(L"PYTHONUTF8", L"1") ||
        !SetEnvironmentVariableW(L"HF_HUB_OFFLINE", L"1") ||
        !SetEnvironmentVariableW(L"TRANSFORMERS_OFFLINE", L"1")) {
        return 0;
    }

    if (!join_path(value, 32768, root, L"cache\\huggingface") ||
        !SetEnvironmentVariableW(L"HF_HOME", value) ||
        !join_path(value, 32768, root, L"cache\\huggingface\\hub") ||
        !SetEnvironmentVariableW(L"HF_HUB_CACHE", value) ||
        !join_path(value, 32768, root, L"cache\\huggingface\\transformers") ||
        !SetEnvironmentVariableW(L"TRANSFORMERS_CACHE", value) ||
        !join_path(value, 32768, root, L"cache\\numba") ||
        !SetEnvironmentVariableW(L"NUMBA_CACHE_DIR", value) ||
        !join_path(value, 32768, root, L"cache\\torch") ||
        !SetEnvironmentVariableW(L"TORCH_HOME", value) ||
        !join_path(value, 32768, root, L"cache\\temp") ||
        !SetEnvironmentVariableW(L"TEMP", value) ||
        !SetEnvironmentVariableW(L"TMP", value)) {
        return 0;
    }
    written = swprintf(
        value,
        32768,
        L"%ls\\bin;%ls\\runtime;%ls\\runtime\\Scripts;%ls\\runtime\\Lib\\site-packages\\torch\\lib;%ls\\System32;%ls",
        root, root, root, root, system_root, system_root
    );
    if (written < 0 || written >= 32768 || !SetEnvironmentVariableW(L"PATH", value)) {
        return 0;
    }
    return 1;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command_line, int show_command) {
    wchar_t executable[32768];
    wchar_t root[32768];
    wchar_t pythonw[32768];
    wchar_t script[32768];
    wchar_t command[65536];
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    DWORD length;
    int written;
    wchar_t *separator;

    launcher_instance = instance;
    (void)previous;
    (void)command_line;
    (void)show_command;

    length = GetModuleFileNameW(NULL, executable, 32768);
    if (length == 0 || length >= 32768) {
        show_error(IDS_ERROR_EXE_DIR);
        return 2;
    }
    wcscpy(root, executable);
    separator = wcsrchr(root, L'\\');
    if (separator == NULL) {
        show_error(IDS_ERROR_INVALID_PATH);
        return 2;
    }
    *separator = L'\0';

    if (!join_path(pythonw, 32768, root, L"runtime\\pythonw.exe") ||
        !join_path(script, 32768, root, L"app\\scripts\\run_gui.py")) {
        show_error(IDS_ERROR_PATH_TOO_LONG);
        return 2;
    }
    if (GetFileAttributesW(pythonw) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        show_error(IDS_ERROR_INCOMPLETE);
        return 2;
    }

    if (!set_root_environment(root)) {
        show_error(IDS_ERROR_ENVIRONMENT);
        return 2;
    }
    written = swprintf(command, 65536, L"\"%ls\" \"%ls\"", pythonw, script);
    if (written < 0 || written >= 65536) {
        show_error(IDS_ERROR_PATH_TOO_LONG);
        return 2;
    }
    startup.cb = sizeof(startup);
    if (!CreateProcessW(
            pythonw,
            command,
            NULL,
            NULL,
            FALSE,
            CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
            NULL,
            root,
            &startup,
            &process)) {
        wchar_t message[512];
        wchar_t format[256];
        wchar_t title[128];
        written = swprintf(
            message,
            512,
            load_string(IDS_ERROR_START_FORMAT, format, 256),
            GetLastError()
        );
        if (written < 0 || written >= 512) {
            wcscpy(message, load_string(IDS_ERROR_START_GENERIC, format, 256));
        }
        MessageBoxW(NULL, message, load_string(IDS_APP_TITLE, title, 128), MB_ICONERROR);
        return 3;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
