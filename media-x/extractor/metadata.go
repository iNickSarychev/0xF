package extractor

import (
	"fmt"
	"net/http"
	"time"

	"github.com/otiai10/opengraph/v2"
)

// ExtractionResult содержит данные, найденные на странице
type ExtractionResult struct {
	ImageURL string
	Title    string
}

// ExtractMainImage — главная функция-оркестратор Pipeline'а
func ExtractMainImage(url string) (*ExtractionResult, error) {
	// 1. Попытка через OpenGraph
	res, err := FromMetadata(url)
	if err == nil && res.ImageURL != "" {
		return res, nil
	}

	// 2. Если OG пуст или ошибка, пробуем Readability
	return FromReadability(url)
}

// FromMetadata извлекает данные через OpenGraph теги
func FromMetadata(urlStr string) (*ExtractionResult, error) {
	fmt.Printf("[DEBUG] OG: Fetching URL: %s\n", urlStr)

	client := &http.Client{Timeout: 7 * time.Second}
	req, err := http.NewRequest("GET", urlStr, nil)
	if err != nil {
		return nil, err
	}

	// Маскировка под реальный браузер
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
	req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8")

	resp, err := client.Do(req)
	if err != nil {
		fmt.Printf("[DEBUG] OG: Error fetching: %v\n", err)
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		fmt.Printf("[DEBUG] OG: Received non-200 status: %d\n", resp.StatusCode)
		return nil, fmt.Errorf("status code %d", resp.StatusCode)
	}

	// В v2 парсинг делается через создание объекта с указанием URL
	og := opengraph.New(urlStr)
	if err := og.Parse(resp.Body); err != nil {
		return nil, err
	}

	if len(og.Image) == 0 {
		fmt.Printf("[DEBUG] OG: No images found in metadata (Title: %s)\n", og.Title)
		return nil, fmt.Errorf("no open graph images found")
	}

	fmt.Printf("[DEBUG] OG: Found image: %s\n", og.Image[0].URL)
	return &ExtractionResult{
		ImageURL: og.Image[0].URL,
		Title:    og.Title,
	}, nil
}
