#include <windows.h>
#include <wchar.h>

static int join_path(wchar_t *output, size_t capacity, const wchar_t *root, const wchar_t *relative) {
    int written = swprintf(output, capacity, L"%ls\\%ls", root, relative);
    return written > 0 && (size_t)written < capacity;
}

static void set_root_environment(const wchar_t *root) {
    wchar_t value[32768];
    wchar_t system_root[MAX_PATH];
    GetEnvironmentVariableW(L"SystemRoot", system_root, MAX_PATH);

    SetEnvironmentVariableW(L"JP2ZH_PORTABLE_ROOT", root);
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
    SetEnvironmentVariableW(L"PYTHONDONTWRITEBYTECODE", L"1");
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    SetEnvironmentVariableW(L"HF_HUB_OFFLINE", L"1");
    SetEnvironmentVariableW(L"TRANSFORMERS_OFFLINE", L"1");

    swprintf(value, 32768, L"%ls\\cache\\huggingface", root);
    SetEnvironmentVariableW(L"HF_HOME", value);
    swprintf(value, 32768, L"%ls\\cache\\huggingface\\hub", root);
    SetEnvironmentVariableW(L"HF_HUB_CACHE", value);
    swprintf(value, 32768, L"%ls\\cache\\huggingface\\transformers", root);
    SetEnvironmentVariableW(L"TRANSFORMERS_CACHE", value);
    swprintf(value, 32768, L"%ls\\cache\\numba", root);
    SetEnvironmentVariableW(L"NUMBA_CACHE_DIR", value);
    swprintf(value, 32768, L"%ls\\cache\\torch", root);
    SetEnvironmentVariableW(L"TORCH_HOME", value);
    swprintf(value, 32768, L"%ls\\cache\\temp", root);
    SetEnvironmentVariableW(L"TEMP", value);
    SetEnvironmentVariableW(L"TMP", value);
    swprintf(
        value,
        32768,
        L"%ls\\bin;%ls\\runtime;%ls\\runtime\\Scripts;%ls\\runtime\\Lib\\site-packages\\torch\\lib;%ls\\System32;%ls",
        root, root, root, root, system_root, system_root
    );
    SetEnvironmentVariableW(L"PATH", value);
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
    wchar_t *separator;

    (void)instance;
    (void)previous;
    (void)command_line;
    (void)show_command;

    length = GetModuleFileNameW(NULL, executable, 32768);
    if (length == 0 || length >= 32768) {
        MessageBoxW(NULL, L"无法确定程序所在目录。", L"jp2zh 字幕工具", MB_ICONERROR);
        return 2;
    }
    wcscpy(root, executable);
    separator = wcsrchr(root, L'\\');
    if (separator == NULL) {
        MessageBoxW(NULL, L"启动路径无效。", L"jp2zh 字幕工具", MB_ICONERROR);
        return 2;
    }
    *separator = L'\0';

    if (!join_path(pythonw, 32768, root, L"runtime\\pythonw.exe") ||
        !join_path(script, 32768, root, L"app\\scripts\\run_gui.py")) {
        MessageBoxW(NULL, L"绿色目录路径过长。", L"jp2zh 字幕工具", MB_ICONERROR);
        return 2;
    }
    if (GetFileAttributesW(pythonw) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(
            NULL,
            L"绿色版文件不完整：找不到内置 Python 或 GUI 脚本。",
            L"jp2zh 字幕工具",
            MB_ICONERROR
        );
        return 2;
    }

    set_root_environment(root);
    swprintf(command, 65536, L"\"%ls\" \"%ls\"", pythonw, script);
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
        swprintf(message, 512, L"无法启动 GUI（Windows 错误 %lu）。", GetLastError());
        MessageBoxW(NULL, message, L"jp2zh 字幕工具", MB_ICONERROR);
        return 3;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
