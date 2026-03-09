CREATE TABLE IF NOT EXISTS backtest_results (
  run_id CHAR(36) NOT NULL,
  ticker VARCHAR(10) NOT NULL,
  rule_type VARCHAR(50) NOT NULL,
  rule_id VARCHAR(100) NULL,
  params_json JSON NOT NULL,
  metrics_json JSON NOT NULL,
  equity_curve_json JSON NULL,
  trades_json JSON NULL,
  data_hash CHAR(64) NULL,
  status ENUM('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED') NOT NULL,
  error_message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  completed_at DATETIME NULL,
  PRIMARY KEY (run_id),
  KEY idx_backtest_results_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
