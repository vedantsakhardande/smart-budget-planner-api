import os
from flask import Flask, jsonify, request
from pymongo import MongoClient
from datetime import datetime
import pytz
from decouple import config
from flasgger import Swagger

app = Flask(__name__)
swagger = Swagger(app)

# Access environment variables
app.config['cluster_username'] = config('CLUSTER_USERNAME')
app.config['cluster_password'] = config('CLUSTER_PASSWORD')
app.config['cluster_uri'] = config('CLUSTER_URI')

# Replace 'YOUR_CONNECTION_URI' with your MongoDB Atlas connection string
app.config['MONGO_URI'] = "mongodb+srv://{}:{}@{}/?retryWrites=true&w=majority".format(app.config['cluster_username'], app.config['cluster_password'], app.config['cluster_uri'])

'mongodb+srv://mongocluster:mongocluster@mongocluster.rj9zaak.mongodb.net/?retryWrites=true&w=majority'

# Initialize PyMongo
mongo = MongoClient(app.config['MONGO_URI'])

# Access a specific database and collection
db = mongo.get_database('smart-budget-planner')
collection = db['transactions']


@app.route('/transactions', methods=['GET'])
def get_transactions():
    """
    Get transactions within a date range.

    ---
    parameters:
      - name: from
        in: query
        type: string
        format: date
        required: true
        description: Start date (YYYY-MM-DD)
      - name: to
        in: query
        type: string
        format: date
        required: true
        description: End date (YYYY-MM-DD)
    responses:
      200:
        description: List of transactions within the date range.
        schema:
          type: object
          properties:
            transactions:
              type: array
              items:
                type: object
                properties:
                  _id:
                    type: string
                  amount:
                    type: number
                  description:
                    type: string
                  timestamp:
                    type: string
                  type:
                    type: string
      500:
        description: Internal Server Error.
    """
    try:
        # Get the 'from' and 'to' date parameters from the query string
        from_date = request.args.get('from')
        to_date = request.args.get('to')

        # Convert 'from' and 'to' date strings to datetime objects and explicitly set them to UTC timezone
        from_date = datetime.strptime(from_date, '%Y-%m-%d')
        from_date = pytz.utc.localize(from_date)

        # Adjust 'to_date' to include the end of the day (23:59:59.999999)
        to_date = datetime.strptime(to_date, '%Y-%m-%d')
        to_date = pytz.utc.localize(to_date).replace(hour=23, minute=59, second=59, microsecond=999999)

        # Define the query to filter transactions by date range
        query = {"timestamp": {"$gte": from_date, "$lte": to_date}}

        # Use the query to retrieve transactions in the specified date range
        transactions_in_range = list(collection.find(query))

        # Convert ObjectId fields to strings
        for transaction in transactions_in_range:
            transaction['_id'] = str(transaction['_id'])

        return jsonify({"transactions": transactions_in_range})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/transactions', methods=['POST'])
def create_transaction():
    """
    Create a new transaction.

    ---
    parameters:
      - name: transaction_data
        in: body
        required: true
        schema:
          type: object
          properties:
            amount:
              type: number
            description:
              type: string
            type:
              type: string
    responses:
      201:
        description: Transaction created successfully.
        schema:
          type: object
          properties:
            message:
              type: string
            transaction:
              type: object
      500:
        description: Internal Server Error.
    """
    try:
        # Get the transaction data from the request JSON
        transaction_data = request.get_json()
        transaction_data['timestamp'] = datetime.now()

        # Insert the new transaction into the collection
        result = collection.insert_one(transaction_data)

        # Return the newly created transaction with its generated ObjectId
        new_transaction_id = str(result.inserted_id)
        transaction_data['_id'] = new_transaction_id
        return jsonify({"message": "Transaction created successfully", "transaction": transaction_data}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
