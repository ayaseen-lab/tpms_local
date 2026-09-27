// Windows entry launcher for TPMS Suite 2.0.
// Cross-compile: GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -o TPMS_Suite.exe ./windows/launcher
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
)

func main() {
	exe, err := os.Executable()
	if err != nil {
		fmt.Fprintln(os.Stderr, "cannot resolve executable:", err)
		os.Exit(1)
	}
	root := filepath.Dir(exe)

	// Prefer full PyInstaller package next to this launcher.
	packaged := filepath.Join(root, "dist", "TPMS_Suite", "TPMS_Suite.exe")
	if st, err := os.Stat(packaged); err == nil && !st.IsDir() {
		runDetached(packaged, root)
		return
	}

	bat := filepath.Join(root, "Start TPMS Suite.bat")
	if st, err := os.Stat(bat); err == nil && !st.IsDir() {
		cmd := exec.Command("cmd.exe", "/c", bat)
		cmd.Dir = root
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		cmd.Stdin = os.Stdin
		if err := cmd.Run(); err != nil {
			if ee, ok := err.(*exec.ExitError); ok {
				os.Exit(ee.ExitCode())
			}
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}

	fmt.Fprintln(os.Stderr, "TPMS Suite launcher: missing Start TPMS Suite.bat")
	fmt.Fprintln(os.Stderr, "Run Setup_Windows.bat once, or build with Build_Windows_Installer.bat")
	fmt.Fprintln(os.Stderr, "Root:", root)
	waitEnter()
	os.Exit(1)
}

func runDetached(path, dir string) {
	cmd := exec.Command(path)
	cmd.Dir = dir
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: false}
	if err := cmd.Start(); err != nil {
		fmt.Fprintln(os.Stderr, "failed to start packaged app:", err)
		waitEnter()
		os.Exit(1)
	}
}

func waitEnter() {
	fmt.Fprintln(os.Stderr, "Press Enter to close…")
	fmt.Scanln()
}
