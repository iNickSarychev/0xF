package extractor

import (
	"fmt"
	"net/http"
	"net/url"
	"time"

	"github.com/go-shiori/go-readability"
)

// FromReadability анализирует DOM-дерево для поиска основного контента и фото
func FromReadability(u string) (*ExtractionResult, error) {
	client := &http.Client{Timeout: 10 * time.Second}
	
	parsedURL, err := url.Parse(u)
	if err != nil {
		return nil, fmt.Errorf("invalid url: %v", err)
	}

	req, err := http.NewRequest("GET", u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("readability fetch status: %d", resp.StatusCode)
	}

	// Извлекаем "чистую" версию страницы
	article, err := readability.FromReader(resp.Body, parsedURL)
	if err != nil {
		return nil, fmt.Errorf("readability error: %v", err)
	}

	// Readability возвращает TopImage в структуре Article
	if article.Image == "" {
		return nil, fmt.Errorf("no main image found via readability")
	}

	return &ExtractionResult{
		ImageURL: article.Image,
		Title:    article.Title,
	}, nil
}
