export const TOOLS = [
  { 
    type: "function", 
    function: { 
      name: "create_channel", 
      description: "Создать канал", 
      parameters: { type: "object", properties: { name: { type: "string" }, type: { type: "string", enum: ["text", "voice"] } }, required: ["name", "type"] } 
    } 
  },
];
export const DANGEROUS = new Set();