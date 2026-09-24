package ramify

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

var pages = map[string]string{
	"": "console.html", "shop": "console.html", "demo": "demo.html", "david-demo": "david-demo.html",
	"tour": "tour.html", "cart": "cart.html", "agents": "agents.html", "review": "review.html",
	"activity": "activity.html", "human-receipt": "human-receipt.html", "technical": "technical.html",
	"proof-pack": "proof-pack.html", "about": "about.html", "help": "help.html",
}

func (s *Server) pageOrAsset(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimPrefix(r.URL.Path, "/")
	if page, ok := pages[name]; ok {
		http.ServeFile(w, r, filepath.Join(s.root, "frontend", "pages", page))
		return
	}
	clean := filepath.Base(name)
	if clean != name || clean == "." || clean == "" {
		http.NotFound(w, r)
		return
	}

	ext := strings.ToLower(filepath.Ext(clean))
	var dir string
	switch ext {
	case ".js":
		dir = filepath.Join(s.root, "frontend", "scripts")
	case ".css":
		dir = filepath.Join(s.root, "frontend", "styles")
	case ".png":
		dir = filepath.Join(s.root, "product_images")
	default:
		http.NotFound(w, r)
		return
	}
	path := filepath.Join(dir, clean)
	if st, err := os.Stat(path); err == nil && !st.IsDir() {
		http.ServeFile(w, r, path)
		return
	}
	http.NotFound(w, r)
}

func frontendBuildID(root string) string {
	h := sha256.New()
	base := filepath.Join(root, "frontend")
	_ = filepath.Walk(base, func(path string, info os.FileInfo, err error) error {
		if err != nil || info == nil || info.IsDir() {
			return nil
		}
		rel, _ := filepath.Rel(base, path)
		h.Write([]byte(filepath.ToSlash(rel)))
		if b, e := os.ReadFile(path); e == nil {
			h.Write(b)
		}
		return nil
	})
	return hex.EncodeToString(h.Sum(nil))[:8]
}
