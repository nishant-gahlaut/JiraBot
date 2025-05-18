import torch
from transformers import DistilBertTokenizerFast, DistilBertModel
import joblib
import torch.nn.functional as F

# Model class (must match training)
class DistilBertMultiOutput(torch.nn.Module):
    def __init__(self, model_name, num_labels_1, num_labels_2):
        super(DistilBertMultiOutput, self).__init__()
        self.bert = DistilBertModel.from_pretrained(model_name)
        self.dropout = torch.nn.Dropout(0.3)
        self.classifier1 = torch.nn.Linear(self.bert.config.hidden_size, num_labels_1)
        self.classifier2 = torch.nn.Linear(self.bert.config.hidden_size, num_labels_2)

    def forward(self, input_ids, attention_mask=None):
        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        pooled_output = outputs.last_hidden_state[:, 0]
        pooled_output = self.dropout(pooled_output)
        logits1 = self.classifier1(pooled_output)
        logits2 = self.classifier2(pooled_output)
        return {"logits1": logits1, "logits2": logits2}

# Load everything
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

tokenizer = DistilBertTokenizerFast.from_pretrained("tokenizer/")
priority_encoder = joblib.load("priority_encoder.pkl")
issue_type_encoder = joblib.load("issue_type_encoder.pkl")

model = DistilBertMultiOutput("distilbert-base-uncased", len(priority_encoder.classes_), len(issue_type_encoder.classes_))
model.load_state_dict(torch.load("best_model.pt", map_location=device))
model.to(device)
model.eval()

# Inference function
def predict(text):
    enc = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=256)
    input_ids = enc["input_ids"].to(device)
    attention_mask = enc["attention_mask"].to(device)

    with torch.no_grad():
        outputs = model(input_ids, attention_mask)
        pred_priority = torch.argmax(F.softmax(outputs["logits1"], dim=1), dim=1).item()
        pred_issue = torch.argmax(F.softmax(outputs["logits2"], dim=1), dim=1).item()

    priority_label = priority_encoder.inverse_transform([pred_priority])[0]
    issue_label = issue_type_encoder.inverse_transform([pred_issue])[0]

    return priority_label, issue_label

# Example
text = "Our Jira instance is unresponsive and critical tickets are not getting updated."
priority, issue_type = predict(text)
print("Predicted Priority:", priority)
print("Predicted Issue Type:", issue_type) 