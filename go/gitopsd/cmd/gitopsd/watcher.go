package gitopsd

import (
	"crypto/sha256"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"
)

// computeSHA256 computes the SHA256 hash of a file's content.
func computeSHA256(filePath string) (string, error) {
	file, err := os.Open(filePath)
	if err != nil {
		return "", err
	}
	defer file.Close()

	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}

	return fmt.Sprintf("%x", hash.Sum(nil)), nil
}

// ScanManifests walks the provided directory path and returns a map
// of all .yaml or .yml files to their SHA256 content hash.
func ScanManifests(path string) map[string]string {
	fileHashes := make(map[string]string)

	err := filepath.Walk(path, func(filePath string, info os.FileInfo, err error) error {
		if err != nil {
			log.Printf("Warning: Error accessing path %s: %v", filePath, err)
			return filepath.SkipDir
		}

		if info.IsDir() {
			return nil // Continue walking
		}

		ext := strings.ToLower(filepath.Ext(filePath))
		if ext != ".yaml" && ext != ".yml" {
			return nil // Not a manifest file
		}

		hash, hashErr := computeSHA256(filePath)
		if hashErr != nil {
			log.Printf("Warning: Could not compute hash for %s: %v", filePath, hashErr)
			return nil // Continue walking
		}

		fileHashes[filePath] = hash
		return nil
	})

	if err != nil {
		log.Printf("Error walking manifest directory %s: %v", path, err)
	}

	return fileHashes
}

// DetectChanges compares two file hash maps and returns a list of
// files that were added or whose hashes have changed.
func DetectChanges(oldMap, newMap map[string]string) []string {
	var changedFiles []string

	for filePath, newHash := range newMap {
		oldHash, exists := oldMap[filePath]
		if !exists || oldHash != newHash {
			changedFiles = append(changedFiles, filePath)
		}
	}

	// Note: This logic intentionally does not detect *deletions*.
	// It only detects additions and modifications.

	return changedFiles
}
