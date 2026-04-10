package main

import (
	"log"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"media-x/extractor"
)

type ExtractionRequest struct {
	URL string `json:"url" binding:"required"`
}

type ExtractionResponse struct {
	Status   string `json:"status"`
	ImageURL string `json:"image_url,omitempty"`
	Title    string `json:"title,omitempty"`
	Error    string `json:"error,omitempty"`
}

func main() {
	r := gin.Default()

	// Увеличиваем таймауты для тяжелых страниц
	s := &http.Server{
		Addr:           ":8080",
		Handler:        r,
		ReadTimeout:    10 * time.Second,
		WriteTimeout:   30 * time.Second,
		MaxHeaderBytes: 1 << 20,
	}

	v1 := r.Group("/v1")
	{
		v1.POST("/extract", handleExtract)
		v1.GET("/health", func(c *gin.Context) {
			c.JSON(200, gin.H{"status": "ok"})
		})
	}

	log.Printf("Media-X Server starting on :8080...")
	if err := s.ListenAndServe(); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}

func handleExtract(c *gin.Context) {
	var req ExtractionRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, ExtractionResponse{
			Status: "error",
			Error:  "Invalid request body or missing URL",
		})
		return
	}

	log.Printf("Processing URL: %s", req.URL)

	// Вызываем наш Pipeline извлечения
	result, err := extractor.ExtractMainImage(req.URL)
	if err != nil {
		log.Printf("Extraction failed for %s: %v", req.URL, err)
		c.JSON(http.StatusPartialContent, ExtractionResponse{
			Status: "error",
			Error:  err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, ExtractionResponse{
		Status:   "success",
		ImageURL: result.ImageURL,
		Title:    result.Title,
	})
}
