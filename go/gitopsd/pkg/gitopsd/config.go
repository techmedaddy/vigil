package gitopsd

import (
	"log"
	"os"

	"gopkg.in/yaml.v3"
)

// Config holds the runtime configuration for the GitOps daemon.
type Config struct {
	Interval      int    `yaml:"interval"`
	ManifestsPath string `yaml:"manifests_path"`
	CollectorURL  string `yaml:"collector_url"`
}

const (
	defaultInterval      = 30
	defaultManifestsPath = "manifests/"
	defaultCollectorURL  = "http://127.0.0.1:8000/api/v1/actions"
)

// LoadConfig reads the configuration file from the specified path.
// It returns a Config struct populated with values from the file,
// falling back to defaults if the file is missing, unreadable,
// or if specific keys are not set.
func LoadConfig(path string) Config {
	// Start with default values
	conf := Config{
		Interval:      defaultInterval,
		ManifestsPath: defaultManifestsPath,
		CollectorURL:  defaultCollectorURL,
	}

	data, err := os.ReadFile(path)
	if err != nil {
		log.Printf("Warning: Could not read config file %s (%v). Using defaults.", path, err)
		return conf
	}

	// Unmarshal into the config struct, overwriting defaults
	if err := yaml.Unmarshal(data, &conf); err != nil {
		log.Printf("Warning: Could not parse config file %s (%v). Using defaults.", path, err)
		// Return the hardcoded defaults in case of partial unmarshal
		return Config{
			Interval:      defaultInterval,
			ManifestsPath: defaultManifestsPath,
			CollectorURL:  defaultCollectorURL,
		}
	}

	// Ensure zero-values from YAML are reset to defaults
	if conf.Interval <= 0 {
		conf.Interval = defaultInterval
	}
	if conf.ManifestsPath == "" {
		conf.ManifestsPath = defaultManifestsPath
	}
	if conf.CollectorURL == "" {
		conf.CollectorURL = defaultCollectorURL
	}

	return conf
}
