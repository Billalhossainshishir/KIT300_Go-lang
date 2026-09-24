package ramifyos

import "embed"

// Assets documents the complete read-only project payload carried by the Go edition.
// The normal launcher serves files from the release folder so client edits remain visible.
//
//go:embed VERSION.txt frontend/** data/** product_images/** demo_runtime_seed/**
var Assets embed.FS
