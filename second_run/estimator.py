# =============================================================================
# Use this file to define your custom model/estimator.
# Below is an example of how to build a simple estimator using scikit-learn
# to predict house price
# =============================================================================
from typing import Self

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import LabelEncoder


class HousePredictionModel:
    """
    Following sklearn principle to define a custom estimator.
    It should two methods: fit and predict. The predict function
    should ensure that the number of inputs should be the same as the
    number of outputs.
    """

    def __init__(self) -> None:
        self.model: LinearRegression
        # encoders / statistics for new dataset
        self.furnishing_encoder: LabelEncoder
        self.mean_area: float
        self.mean_bedrooms: float
        self.mean_bathrooms: float

    def transform(self, raw_x: pd.DataFrame) -> pd.DataFrame:
        """
        Transform the input data to the format that the model can understand.

        Args:
        ----
            raw_x (HouseFrame): Raw Data

        Returns:
        -------
            pd.DataFrame: Features for the model

        """
        # --- normalize and coerce types ---
        raw = raw_x.copy()

        # Numeric columns
        for col in ["area", "bedrooms", "bathrooms", "stories", "parking"]:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")

        # Fill numeric missing values with learned statistics or sensible defaults
        raw["area"] = raw["area"].fillna(self.mean_area)
        raw["bedrooms"] = raw["bedrooms"].fillna(self.mean_bedrooms)
        raw["bathrooms"] = raw["bathrooms"].fillna(self.mean_bathrooms)
        raw["stories"] = raw["stories"].fillna(1)
        raw["parking"] = raw["parking"].fillna(0)

        # Boolean-like columns: ensure 0/1
        for col in ["mainroad", "guestroom", "basement", "hotwaterheating", "airconditioning", "prefarea"]:
            raw[col] = raw[col].map({True: 1, False: 0, "True": 1, "False": 0, "true": 1, "false": 0}).fillna(0).astype(int)

        # Furnishing status: categorical encoder
        raw["furnishingstatus"] = raw["furnishingstatus"].astype(str).fillna("none")
        furnishing_enc = self.furnishing_encoder.transform(raw["furnishingstatus"])

        return pd.DataFrame({
            "area": np.log1p(raw["area"]).values,
            "bedrooms": raw["bedrooms"].astype(int).values,
            "bathrooms": raw["bathrooms"].astype(int).values,
            "stories": raw["stories"].astype(int).values,
            "mainroad": raw["mainroad"].astype(int).values,
            "guestroom": raw["guestroom"].astype(int).values,
            "basement": raw["basement"].astype(int).values,
            "hotwaterheating": raw["hotwaterheating"].astype(int).values,
            "airconditioning": raw["airconditioning"].astype(int).values,
            "parking": raw["parking"].astype(int).values,
            "prefarea": raw["prefarea"].astype(int).values,
            "furnishingstatus": furnishing_enc,
        })

    @property
    def input_features(self) -> list[str]:
        """Returns features used in the model

        Returns:
            list[str]: _description_
        """
        return [
            "area",
            "bedrooms",
            "bathrooms",
            "stories",
            "mainroad",
            "guestroom",
            "basement",
            "hotwaterheating",
            "airconditioning",
            "parking",
            "prefarea",
            "furnishingstatus",
        ]

    def fit(self, raw_x: pd.DataFrame, raw_y: npt.NDArray[np.float64]) -> Self:
        """
        Trains the model.

        Args:
        ----
            raw_x (HouseFrame): Raw Input data
            raw_y (npt.NDArray[np.float64]): House prices

        Returns:
        -------
            Self: Returns the same instance of the model

        """
        # Compute statistics for numeric imputation
        self.mean_area = raw_x["area"].median() if "area" in raw_x.columns else 0.0
        self.mean_bedrooms = raw_x["bedrooms"].median() if "bedrooms" in raw_x.columns else 1.0
        self.mean_bathrooms = raw_x["bathrooms"].median() if "bathrooms" in raw_x.columns else 1.0

        # Fit label encoder for furnishingstatus
        self.furnishing_encoder = LabelEncoder()
        self.furnishing_encoder.fit(raw_x.get("furnishingstatus", pd.Series("none")).astype(str))

        # Train linear regression on transformed features
        self.model = LinearRegression()
        self.model.fit(self.transform(raw_x), raw_y)
        return self

    def predict(self, raw_x: pd.DataFrame) -> pd.DataFrame:
        """
        Run the infernece.

        Args:
        ----
            raw_x (HouseFrame): Input raw data

        Returns:
        -------
            HousePredictionData: Generated predictions with additional information

        """
        price = self.model.predict(self.transform(raw_x))
        return pd.DataFrame({"price": price, "is_valid": (price > 0), "info": None})