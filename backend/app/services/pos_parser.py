import pandas as pd
from datetime import datetime, date
from typing import List, Tuple, Dict
from io import BytesIO
import logging

logger = logging.getLogger(__name__)


class POSParseError(Exception):
    """Raised when POS CSV parsing fails"""
    pass


class POSParser:
    """Parse and normalize POS CSV files into daily revenue time series"""
    
    REQUIRED_COLUMNS = ["date", "amount"]  # minimum required
    
    @staticmethod
    def parse_csv(file_content: bytes, business_name: str = None) -> Tuple[List[Dict], str]:
        """
        Parse POS CSV file into daily revenue aggregates
        
        Args:
            file_content: Raw CSV file bytes
            business_name: Optional business name from metadata
            
        Returns:
            Tuple of (daily_revenue_list, detected_business_name)
            
        Raises:
            POSParseError: If parsing or validation fails
        """
        try:
            # Read CSV
            df = pd.read_csv(BytesIO(file_content))
            logger.info(f"Loaded CSV with {len(df)} rows and columns: {df.columns.tolist()}")
            
            # Normalize column names (lowercase, strip spaces)
            df.columns = df.columns.str.lower().str.strip()
            
            # Detect business name from data if not provided
            if not business_name and "business_name" in df.columns:
                business_name = df["business_name"].mode()[0] if not df["business_name"].isna().all() else None
            
            # Validate required columns
            POSParser._validate_columns(df)
            
            # Parse and validate dates
            df["parsed_date"] = POSParser._parse_dates(df["date"])
            
            # Parse and validate amounts
            df["parsed_amount"] = POSParser._parse_amounts(df["amount"])
            
            # Filter out invalid rows
            valid_df = df.dropna(subset=["parsed_date", "parsed_amount"])
            if len(valid_df) == 0:
                raise POSParseError("No valid date/amount pairs found in CSV")
            
            logger.info(f"Valid rows: {len(valid_df)}/{len(df)}")
            
            # Aggregate by date (sum all transactions per day)
            daily_revenue = (
                valid_df.groupby("parsed_date")["parsed_amount"]
                .sum()
                .reset_index()
                .rename(columns={"parsed_date": "date", "parsed_amount": "revenue"})
            )
            
            # Fill missing days with zero revenue
            daily_revenue = POSParser._fill_missing_days(daily_revenue)
            
            # Convert to list of dicts for database insertion
            revenue_list = daily_revenue.to_dict("records")
            
            logger.info(f"Parsed {len(revenue_list)} days of revenue data")
            
            return revenue_list, business_name
            
        except Exception as e:
            logger.error(f"POS parsing failed: {e}")
            raise POSParseError(f"Failed to parse POS CSV: {str(e)}")
    
    @staticmethod
    def _validate_columns(df: pd.DataFrame) -> None:
        """Validate that required columns exist"""
        missing_cols = [col for col in POSParser.REQUIRED_COLUMNS if col not in df.columns]
        if missing_cols:
            raise POSParseError(
                f"Missing required columns: {missing_cols}. "
                f"Found: {df.columns.tolist()}"
            )
    
    @staticmethod
    def _parse_dates(date_series: pd.Series) -> pd.Series:
        """Parse dates with multiple format support"""
        try:
            # Try standard date parsing
            parsed = pd.to_datetime(date_series, errors="coerce")
            
            # Check for too many invalid dates
            invalid_count = parsed.isna().sum()
            if invalid_count > len(parsed) * 0.1:  # > 10% invalid
                logger.warning(f"{invalid_count} dates could not be parsed")
            
            return parsed.dt.date
            
        except Exception as e:
            raise POSParseError(f"Date parsing failed: {e}")
    
    @staticmethod
    def _parse_amounts(amount_series: pd.Series) -> pd.Series:
        """Parse monetary amounts, handling currency symbols and formats"""
        try:
            # Remove currency symbols and commas
            cleaned = amount_series.astype(str).str.replace(r"[$,]", "", regex=True)
            
            # Convert to float
            parsed = pd.to_numeric(cleaned, errors="coerce")
            
            # Validate non-negative
            if (parsed < 0).any():
                logger.warning("Found negative amounts in data")
            
            return parsed
            
        except Exception as e:
            raise POSParseError(f"Amount parsing failed: {e}")
    
    @staticmethod
    def _fill_missing_days(df: pd.DataFrame) -> pd.DataFrame:
        """Fill missing days with zero revenue to create complete time series"""
        if len(df) == 0:
            return df
        
        # Create complete date range
        min_date = df["date"].min()
        max_date = df["date"].max()
        all_dates = pd.date_range(start=min_date, end=max_date, freq="D").date
        
        # Create complete dataframe
        complete_df = pd.DataFrame({"date": all_dates})
        
        # Merge with actual data, filling missing with 0
        result = complete_df.merge(df, on="date", how="left")
        result["revenue"] = result["revenue"].fillna(0.0)
        
        return result
