// Windows entry launcher for TPMS Suite 2.0.
// Cross-compile (no console flash):
//
//	GOOS=windows GOARCH=amd64 go build -ldflags="-s -w -H windowsgui" -o TPMS_Suite.exe ./windows/launcher
package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"
)

const (
	createNewProcessGroup = 0x00000200
	detachedProcess       = 0x00000008
	mbOK                  = 0x00000000
	mbIconError           = 0x00000010
)

func main() {
	exe, err := os.Executable()
	if err != nil {
		fail("cannot resolve executable: " + err.Error())
	}
	root := filepath.Dir(exe)

	// 1) Full PyInstaller package (installer / local build).
	packaged := filepath.Join(root, "dist", "TPMS_Suite", "Fyrqom_TPMS_Suite.exe")
	if !fileExists(packaged) {
		packaged = filepath.Join(root, "dist", "TPMS_Suite", "TPMS_Suite.exe")
	}
	if fileExists(packaged) {
		if err := startDetached(packaged, root, nil); err != nil {
			fail("failed to start packaged app: " + err.Error())
		}
		return
	}

	// 2) Source checkout: pythonw/python + main.py.
	// Never call Start TPMS Suite.bat from here — that bat used to re-launch this
	// exe and caused an infinite console flicker loop.
	mainPy := filepath.Join(root, "main.py")
	if fileExists(mainPy) {
		if py, ok := findPython(root); ok {
			if err := startDetached(py, root, []string{mainPy}); err != nil {
				fail("failed to start TPMS Suite: " + err.Error())
			}
			return
		}
		fail("Python was not found.\n\nRun Setup_Windows.bat once, or install Python 3.11+\nfrom python.org (check \"Add python.exe to PATH\").")
	}

	fail("TPMS Suite launcher: nothing to run.\n\nExpected either:\n  dist\\TPMS_Suite\\TPMS_Suite.exe\nor:\n  main.py + Python\n\nRoot: " + root)
}

func findPython(root string) (string, bool) {
	candidates := []string{
		filepath.Join(root, ".venv", "Scripts", "pythonw.exe"),
		filepath.Join(root, ".venv", "Scripts", "python.exe"),
		filepath.Join(os.Getenv("LocalAppData"), "Programs", "Python", "Python312", "pythonw.exe"),
		filepath.Join(os.Getenv("LocalAppData"), "Programs", "Python", "Python312", "python.exe"),
		filepath.Join(os.Getenv("LocalAppData"), "Programs", "Python", "Python311", "pythonw.exe"),
		filepath.Join(os.Getenv("LocalAppData"), "Programs", "Python", "Python311", "python.exe"),
	}
	for _, c := range candidates {
		if fileExists(c) {
			return c, true
		}
	}
	for _, name := range []string{"pythonw.exe", "python.exe"} {
		if p, err := exec.LookPath(name); err == nil && p != "" {
			return p, true
		}
	}
	return "", false
}

func fileExists(path string) bool {
	st, err := os.Stat(path)
	return err == nil && !st.IsDir()
}

func startDetached(path, dir string, args []string) error {
	cmd := exec.Command(path, args...)
	cmd.Dir = dir
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: createNewProcessGroup | detachedProcess,
		HideWindow:    true,
	}
	return cmd.Start()
}

func fail(msg string) {
	user32 := syscall.NewLazyDLL("user32.dll")
	messageBox := user32.NewProc("MessageBoxW")
	title, _ := syscall.UTF16PtrFromString("TPMS Suite")
	body, _ := syscall.UTF16PtrFromString(msg)
	messageBox.Call(0, uintptr(unsafe.Pointer(body)), uintptr(unsafe.Pointer(title)), uintptr(mbOK|mbIconError))
	os.Exit(1)
}
